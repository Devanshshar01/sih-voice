"""Canonical, versioned forensic evidence package (integrity hardening).

WHAT THIS ADDS (without duplicating existing components)
    ``app/core/jcs.py`` already provides RFC 8785 canonicalization and
    ``app/core/merkle.py`` the domain-separated Merkle tree. This module is the
    *schema layer* between them:

      - one canonical, versioned evidence-package representation
        (``sv-evidence-v1``) with explicit artifact metadata;
      - ONE canonicalization function (RFC 8785 via ``jcs``) that every hash
        computation here goes through — no ad-hoc ``json.dumps`` anywhere;
      - the ``EvidenceIntegritySummary``: the single structured answer to
        "is this evidence intact?", keeping the six hash identities distinct
        (artifact hash, package hash, ledger head, Merkle root, PDF hash,
        blockchain tx hash — never collapsed into one field).

DETERMINISM CONTRACT (verified by tests/test_evidence_package.py)
    1. Same semantic package -> exactly the same canonical bytes (RFC 8785:
       key order is byte-sorted, numbers use ECMAScript formatting, no
       insignificant whitespace).
    2. NaN / Infinity are REJECTED (never silently serialized).
    3. Datetimes are normalized to UTC ISO-8601 at second precision before
       hashing; naive datetimes are assumed UTC.
    4. Volatile fields (request ids, PDF timestamps, random UUIDs created
       during serialization, post-package blockchain receipts) are excluded
       from the hashed representation by schema; blockchain anchor data joins
       only through a deliberate later revision (``blockchain_metadata``),
       which changes the package hash by design.
    5. UTF-8 is explicit everywhere (``canonicalize_bytes``).

WHAT IS NOT CLAIMED
    These hashes prove integrity (tamper-evidence) only. They do NOT claim
    court admissibility, legal certification, or immutability.
"""
from __future__ import annotations

import hashlib
import math
from datetime import date, datetime, timezone
from typing import Any, Mapping

from sqlalchemy.orm import Session

from app.core.jcs import canonicalize_bytes
from app.db import models as db_models

__all__ = [
    "EVIDENCE_PACKAGE_SCHEMA_VERSION",
    "EvidencePackageError",
    "normalize_timestamp",
    "build_artifact_metadata",
    "verify_artifact",
    "build_canonical_evidence_package",
    "canonical_package_bytes",
    "package_sha256",
    "verify_package_hash",
    "build_integrity_summary",
]

# Explicit, versioned schema. Bump on any breaking change to the hashed shape.
EVIDENCE_PACKAGE_SCHEMA_VERSION = "sv-evidence-v1"

# Hash-domain separators. Every domain-specific hash prefixes its input so two
# different domains can never produce the same digest from the same bytes.
_DOMAIN_PACKAGE = b"satyavoice:evidence-package:v1:"
_DOMAIN_ARTIFACT = b"satyavoice:evidence-artifact:v1:"


class EvidencePackageError(ValueError):
    """Raised for values that cannot appear in a canonical evidence package."""


def normalize_timestamp(value: Any) -> str | None:
    """Normalize a datetime to a UTC ISO-8601 string at second precision.

    Accepted inputs: ``datetime`` (naive assumed UTC), ISO strings, ``None``.
    The normalized form is what gets hashed, so a package built at 14:00:00.500
    and one built at 14:00:00 in the same second hash identically.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        dt = datetime.fromisoformat(value)
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    else:
        raise EvidencePackageError(f"Unsupported timestamp value: {type(value)!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _reject_bad_numbers(value: Any, _path: str = "package") -> None:
    """Deep-walk the package and reject NaN/Infinity before hashing."""
    if isinstance(value, bool):
        return  # a JSON literal, not a number
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise EvidencePackageError(f"NaN/Infinity not allowed at {_path!r}")
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _reject_bad_numbers(item, f"{_path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_bad_numbers(item, f"{_path}[{index}]")


# ---------------------------------------------------------------- Phase 2 ---
def build_artifact_metadata(
    *,
    artifact_id: str,
    role: str,
    media_type: str,
    content: bytes,
    created_at: Any = None,
    source: str,
    sequence: int | None = None,
) -> dict[str, Any]:
    """Metadata for one evidence artifact, hashing the ACTUAL bytes.

    Never hash a human-readable label when real bytes exist. ``byte_length`` is
    stored so verification can cross-check it against the content.
    """
    if not isinstance(content, (bytes, bytearray)):
        raise EvidencePackageError(f"Artifact {artifact_id!r} must be raw bytes.")
    content = bytes(content)
    digest = hashlib.sha256(_DOMAIN_ARTIFACT + content).hexdigest()
    metadata: dict[str, Any] = {
        "artifact_id": artifact_id,
        "role": role,
        "media_type": media_type,
        "byte_length": len(content),
        "sha256": digest,
        "created_at": normalize_timestamp(created_at or datetime.now(timezone.utc)),
        "source": source,
    }
    if sequence is not None:
        metadata["sequence"] = int(sequence)
    return metadata


def verify_artifact(artifact: Mapping[str, Any], content: bytes) -> bool:
    """True iff *content* still matches the artifact's recorded hash/length."""
    content = bytes(content)
    expected_digest = hashlib.sha256(_DOMAIN_ARTIFACT + content).hexdigest()
    if artifact.get("byte_length") != len(content):
        return False
    return artifact.get("sha256") == expected_digest


# ---------------------------------------------------------------- Phase 1 ---
def build_canonical_evidence_package(
    *,
    evidence_id: str,
    call_id: str | None = None,
    created_at: Any,
    completed_at: Any = None,
    detection: Mapping[str, Any] | None = None,
    acoustic_evidence: Mapping[str, Any] | None = None,
    speaker_verification: Mapping[str, Any] | None = None,
    contextual_analysis: Mapping[str, Any] | None = None,
    risk_summary: Mapping[str, Any] | None = None,
    audio_artifacts: Mapping[str, Any] | None = None,
    model_metadata: Mapping[str, Any] | None = None,
    ledger_metadata: Mapping[str, Any] | None = None,
    merkle_metadata: Mapping[str, Any] | None = None,
    blockchain_metadata: Mapping[str, Any] | None = None,
    verification_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the canonical evidence package (plain dict, no DB, no network).

    The result is a pure value: call ``canonical_package_bytes`` / ``package_sha256``
    on it. Timestamps are normalized here; numeric garbage is rejected here.
    """
    package: dict[str, Any] = {
        "schema_version": EVIDENCE_PACKAGE_SCHEMA_VERSION,
        "evidence_id": str(evidence_id),
        "created_at": normalize_timestamp(created_at),
        "detection": dict(detection or {}),
        "acoustic_evidence": dict(acoustic_evidence or {}),
        "speaker_verification": dict(speaker_verification or {}),
        "contextual_analysis": dict(contextual_analysis or {}),
        "risk_summary": dict(risk_summary or {}),
        "audio_artifacts": dict(audio_artifacts or {}),
        "model_metadata": dict(model_metadata or {}),
        "ledger_metadata": dict(ledger_metadata or {}),
        "merkle_metadata": dict(merkle_metadata or {}),
        "blockchain_metadata": dict(blockchain_metadata or {}),
        "verification_metadata": dict(verification_metadata or {}),
    }
    if call_id is not None:
        package["call_id"] = str(call_id)
    if completed_at is not None:
        package["completed_at"] = normalize_timestamp(completed_at)

    _reject_bad_numbers(package)
    # Fail fast if anything is un-serializable (non-string keys, custom types).
    canonicalize_bytes(package)
    return package


def canonical_package_bytes(package: Mapping[str, Any]) -> bytes:
    """The exact hashed bytes: RFC 8785 canonical JSON encoded as UTF-8."""
    return canonicalize_bytes(package)


def package_sha256(package: Mapping[str, Any]) -> str:
    """Domain-separated SHA-256 of the canonical package bytes."""
    return hashlib.sha256(_DOMAIN_PACKAGE + canonical_package_bytes(package)).hexdigest()


def verify_package_hash(package: Mapping[str, Any], expected_hex: str) -> bool:
    """Recompute the package hash and compare (tamper check)."""
    try:
        return package_sha256(package) == expected_hex
    except Exception:
        return False


# ---------------------------------------------------------------- Phase 5 ---
def build_integrity_summary(db: Session, evidence_id: str) -> dict[str, Any]:
    """The one verification summary (EvidenceIntegritySummary).

    Distinct identities, explicitly separated — never collapsed:
        package_sha256   canonical evidence-package hash
        merkle_root      commitment over the ordered artifact digests
        ledger_head      local hash-chain head for this evidence
        report_sha256    SHA-256 of the generated forensic PDF bytes
        blockchain_*     on-chain anchor state (only when actually confirmed)

    Everything is derived from stored rows — nothing is regenerated, and the
    response contains no freshly generated timestamps.
    """
    from app.services.evidence_anchor import EvidenceAnchorService
    from app.services.merkle_evidence import (
        LEAF_ORDER_RULE,
        TREE_VERSION,
        MerkleEvidenceError,
    )

    merkle_row = (
        db.query(db_models.EvidenceMerklePackage)
        .filter(db_models.EvidenceMerklePackage.evidence_id == evidence_id)
        .first()
    )
    if merkle_row is None:
        raise MerkleEvidenceError(f"Merkle evidence package '{evidence_id}' was not found.")

    report_row = (
        db.query(db_models.EvidenceReportRecord)
        .filter(db_models.EvidenceReportRecord.evidence_id == evidence_id)
        .first()
    )

    legacy_row = (
        db.query(db_models.EvidencePackage)
        .filter(db_models.EvidencePackage.evidence_id == evidence_id)
        .first()
    )
    if legacy_row is not None:
        ledger_status = EvidenceAnchorService(db).verify_ledger(evidence_id)
        ledger_head = legacy_row.local_chain_root
    else:
        # The Merkle package is the primary evidence path; the legacy flat
        # ledger is optional. Absence is not tampering.
        ledger_status = {
            "valid": True,
            "entries_checked": 0,
            "first_invalid_sequence": None,
            "expected_hash": None,
            "actual_hash": None,
            "reason": "no legacy ledger records for this evidence id",
        }
        ledger_head = None

    anchor_status = merkle_row.anchor_status or "unavailable"
    confirmed = anchor_status == "anchored"
    simulated = anchor_status == "dry_run"

    return {
        "evidence_id": evidence_id,
        "schema_version": merkle_row.schema_version,
        "package_sha256": merkle_row.package_hash,
        "merkle_root": merkle_row.merkle_root,
        # Merkle metadata (Phase 4): tree_version / leaf_count / leaf_order_rule /
        # root / generated_at / evidence_id. ``tree_version`` and
        # ``leaf_order_rule`` are DERIVED constants of the construction, never a
        # stored column — a stored copy could be tampered with, a constant cannot.
        "merkle": {
            "tree_version": TREE_VERSION,
            "leaf_count": merkle_row.leaf_count,
            "leaf_order_rule": LEAF_ORDER_RULE,
            "root": merkle_row.merkle_root,
            "generated_at": (
                merkle_row.created_at.isoformat() if merkle_row.created_at else None
            ),
            "evidence_id": evidence_id,
        },
        "ledger_head": ledger_head,
        "ledger": ledger_status,
        "report": {
            "sha256": report_row.report_sha256 if report_row else None,
            "generated_at": (
                report_row.generated_at.isoformat()
                if report_row is not None and report_row.generated_at
                else None
            ),
            "schema_version": report_row.schema_version if report_row else None,
        },
        "blockchain": {
            "status": anchor_status,
            "confirmed": confirmed,
            "simulated": simulated,
            "network": merkle_row.blockchain_network,
            "contract": merkle_row.contract_address,
            # Transaction metadata is surfaced ONLY for a confirmed anchor; a
            # DRY_RUN simulated tx hash must never masquerade as real.
            "tx_hash": merkle_row.anchor_tx_hash if confirmed else None,
            "block_number": merkle_row.anchor_block_number if confirmed else None,
            "anchored_at": (
                merkle_row.anchor_timestamp.isoformat() if merkle_row.anchor_timestamp else None
            ),
            "note": (
                "SIMULATED (dry run) — no transaction was submitted to any blockchain."
                if simulated
                else None
            ),
        },
    }
