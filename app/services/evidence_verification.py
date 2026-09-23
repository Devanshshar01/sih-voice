"""ONE canonical verification path for forensic evidence (Fixes 4 & 5).

WHY THIS MODULE EXISTS
  Before this module the platform had two divergent evidence stores and two
  independent verification implementations:

    * ``POST /forensics/{id}/verify``  -> legacy ``evidence_packages`` (flat hash
      chain written by ``/forensics/register``)
    * ``GET  /forensics/{id}/verify``  -> ``evidence_merkle_packages`` (canonical
      Merkle store written only by ``/merkle/register``)

  Evidence registered through ``/forensics/register`` therefore existed only in
  the legacy store, so the GET path — used by the PDF, the QR code and the
  dashboard integrity panel — returned 404 while POST returned 200.

  This module is now the single implementation behind BOTH routes:

    * :func:`ensure_canonical_merkle_package` — called by ``/forensics/register``
      so one registration creates ONE canonical commitment for the evidence id.
    * :func:`verify_canonical_evidence` — the one verification result; GET and
      POST both call it and can never diverge.

BACKWARD COMPATIBILITY
  ``evidence_packages`` (legacy) rows written before this change are NOT
  migrated, rewritten or deleted. When no canonical Merkle package exists, the
  verifier falls back to the legacy integrity check and labels the result
  ``storage="legacy"`` so the difference is explicit rather than silent.

NO SECOND IMPLEMENTATION
  The legacy-compatibility keys (``evidence_hash``, ``local_chain_root``,
  ``ledger_record_count``, ``anchor_status``, ...) are *aliases* derived from the
  same canonical result — they are not computed by a parallel code path.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db import models as db_models

logger = logging.getLogger("satyavoice.evidence.verification")

# Storage labels surfaced in verification output (never collapsed).
CANONICAL_STORAGE = "canonical"  # evidence_merkle_packages (preferred)
LEGACY_STORAGE = "legacy"        # evidence_packages (backward compatibility)

# The canonical Merkle item name for the frozen evidence snapshot. The item
# bytes are the exact stored canonical JSON, so the Merkle root commits to the
# same snapshot the legacy hash chain committed to.
CANONICAL_PACKAGE_ITEM = "evidence_package"


class EvidenceNotFound(ValueError):
    """Raised when neither the canonical nor the legacy store knows the id."""


def ensure_canonical_merkle_package(
    db: Session,
    *,
    evidence_id: str,
    canonical_payload: str,
    session_id: str | None = None,
    model_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create the canonical Merkle commitment for a registered snapshot.

    Idempotent per ``evidence_id`` (the Merkle service returns the existing
    package rather than inserting a second one), so repeated export clicks never
    create duplicate packages or duplicate roots.

    Anchoring is CANONICAL: ``anchor=True`` submits the Merkle root via
    ``adapter.anchorEvidence(root, evidence_id)`` — never the legacy flat-root
    ``anchor()`` — gated by config (DISABLED -> unavailable, DRY_RUN ->
    simulated, LIVE -> receipt-gated submission behind the owner check). The
    idempotent duplicate path returns BEFORE the anchor block, so repeated
    exports can never re-submit a transaction for the same evidence id.
    """
    from app.services.merkle_evidence import MerkleEvidenceService

    return MerkleEvidenceService(db).register_merkle_package(
        items={CANONICAL_PACKAGE_ITEM: canonical_payload.encode("utf-8")},
        evidence_id=evidence_id,
        session_id=session_id,
        model_metadata=model_metadata,
        anchor=True,
    )


def verify_canonical_evidence(
    db: Session,
    evidence_id: str,
    *,
    verify_on_chain: bool = True,
) -> dict[str, Any]:
    """The single verification result shared by GET and POST ``/verify``.

    Raises :class:`EvidenceNotFound` when the id is unknown to both stores.
    """
    canonical_row = (
        db.query(db_models.EvidenceMerklePackage)
        .filter(db_models.EvidenceMerklePackage.evidence_id == evidence_id)
        .first()
    )
    if canonical_row is not None:
        return _canonical_result(db, evidence_id, verify_on_chain=verify_on_chain)

    legacy_row = (
        db.query(db_models.EvidencePackage)
        .filter(db_models.EvidencePackage.evidence_id == evidence_id)
        .first()
    )
    if legacy_row is not None:
        return _legacy_result(db, evidence_id)

    raise EvidenceNotFound(f"Evidence package '{evidence_id}' was not found.")


# --------------------------------------------------------------- internals ---


def _report_block(db: Session, evidence_id: str) -> dict[str, Any]:
    """The stored forensic-report hash (hashed outside the PDF, never inside)."""
    row = (
        db.query(db_models.EvidenceReportRecord)
        .filter(db_models.EvidenceReportRecord.evidence_id == evidence_id)
        .first()
    )
    return {
        "sha256": row.report_sha256 if row else None,
        "generated_at": (
            row.generated_at.isoformat() if row is not None and row.generated_at else None
        ),
        "schema_version": row.schema_version if row else None,
    }


def _canonical_result(
    db: Session,
    evidence_id: str,
    *,
    verify_on_chain: bool,
) -> dict[str, Any]:
    """Canonical verification: Merkle store + ledger, recomputed server-side."""
    from app.services.evidence_package import build_integrity_summary
    from app.services.merkle_evidence import MerkleEvidenceService

    summary = build_integrity_summary(db, evidence_id)
    merkle = MerkleEvidenceService(db).verify_merkle_package(
        evidence_id, verify_on_chain=verify_on_chain
    )

    ledger_valid = bool(summary["ledger"]["valid"])
    valid = bool(merkle["valid"]) and ledger_valid
    blockchain = summary["blockchain"]
    confirmed = bool(blockchain["confirmed"])

    legacy_row = (
        db.query(db_models.EvidencePackage)
        .filter(db_models.EvidencePackage.evidence_id == evidence_id)
        .first()
    )

    return {
        # --- canonical identities (kept distinct, never collapsed) ----------
        **summary,
        "canonical": True,
        "storage": CANONICAL_STORAGE,
        "valid": valid,
        "integrity": {
            "package_hash_integrity": merkle["package_hash_integrity"],
            "merkle_root_integrity": merkle["merkle_root_integrity"],
            "items_all_verified": merkle["items_all_verified"],
            "evidence_id_matches": merkle["evidence_id_matches"],
        },
        "leaf_count": merkle["leaf_count"],
        "leaf_names": merkle["leaf_names"],
        # --- legacy-compatibility aliases (same derivation, no second impl) --
        "evidence_hash": summary["package_sha256"],
        "evidence_hash_integrity": merkle["package_hash_integrity"],
        "local_chain_root": summary["ledger_head"],
        "local_chain_status": legacy_row.local_chain_status if legacy_row else None,
        "local_chain_integrity": ledger_valid,
        "ledger_record_count": summary["ledger"]["entries_checked"],
        "public_anchor_consistent": confirmed,
        "anchor_status": blockchain["status"],
        "blockchain_network": blockchain["network"],
        "contract_address": blockchain["contract"],
        # Transaction metadata is surfaced ONLY for a confirmed anchor.
        "tx_hash": blockchain["tx_hash"],
        "anchor_timestamp": blockchain["anchored_at"],
        "failure_reason": legacy_row.failure_reason if legacy_row else None,
        # An on-chain query is only meaningful for a real (non-simulated) anchor.
        "on_chain_verified": merkle["on_chain_verified"],
    }


def _legacy_result(db: Session, evidence_id: str) -> dict[str, Any]:
    """Backward-compatible verification for pre-canonical evidence.

    Used only when no canonical Merkle package exists for the id. Existing
    legacy evidence stays readable and verifiable; nothing is rewritten.
    """
    from app.services.evidence_anchor import EvidenceAnchorService

    service = EvidenceAnchorService(db)
    legacy = service.verify_evidence_package(evidence_id)  # raises ValueError if absent
    ledger = service.verify_ledger(evidence_id)

    legacy_row = (
        db.query(db_models.EvidencePackage)
        .filter(db_models.EvidencePackage.evidence_id == evidence_id)
        .first()
    )
    anchor_confirmed = legacy.get("anchor_status") in {"anchored", "confirmed"}
    valid = bool(legacy.get("evidence_hash_integrity")) and bool(
        legacy.get("local_chain_integrity")
    )

    return {
        # Every legacy field is preserved verbatim for existing consumers.
        **legacy,
        "canonical": False,
        "storage": LEGACY_STORAGE,
        "valid": valid,
        "schema_version": legacy_row.schema_version if legacy_row else None,
        # Canonical identities: absent for legacy-only evidence. There is no
        # Merkle commitment, so merkle_root stays null — never faked.
        "package_sha256": legacy.get("evidence_hash"),
        "merkle_root": None,
        "ledger_head": legacy.get("local_chain_root"),
        "ledger": ledger,
        "report": _report_block(db, evidence_id),
        "blockchain": {
            "status": legacy.get("anchor_status") or "unavailable",
            "confirmed": anchor_confirmed,
            "simulated": False,
            "network": legacy.get("blockchain_network"),
            "contract": legacy.get("contract_address"),
            "tx_hash": legacy.get("tx_hash") if anchor_confirmed else None,
            "block_number": None,
            "anchored_at": legacy.get("anchor_timestamp"),
            "note": (
                "Legacy (pre-canonical) evidence: verified from the flat "
                "hash-chain store."
            ),
        },
        "integrity": {
            "package_hash_integrity": legacy.get("evidence_hash_integrity"),
            "merkle_root_integrity": None,
            "items_all_verified": None,
            "evidence_id_matches": None,
        },
        "leaf_count": None,
        "leaf_names": None,
    }
