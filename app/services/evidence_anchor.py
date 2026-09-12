"""Evidence anchoring and verification for finalized forensic packages.

This module maintains a local append-only integrity ledger for forensic
evidence packages and provides deterministic verification.

Chain-of-custody model (the defensible version):
  * The ledger is GLOBAL and append-only. Every record links
    ``previous_record_hash`` to the previous record's ``chain_root_hash``,
    spanning ALL packages in registration order (record_id ASC).
  * A record's ``record_hash`` covers: previous_record_hash, the verbatim
    ``timestamp_hashed`` string (stored exactly as hashed — never re-derived
    from a lossy DB round-trip), schema version, and the evidence digest.
  * ``chain_root_hash`` = H(record_hash || previous_record_hash) — the
    cumulative chain tip at the time of this record.
  * Package verification checks (a) payload-hash integrity, (b) that this
    package's records are internally consistent AND link to the global chain
    through the correct ``previous_record_hash``, (c) the stored chain root
    matches the last of this package's records.
  * ``verify_full_chain`` walks the ENTIRE ledger from GENESIS independently
    — the tamper-evidence primitive an auditor runs without trusting any
    per-package bookkeeping.

Blockchain anchoring is intentionally isolated behind the anchor adapter so
it can be enabled or disabled without changing the rest of the application.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app import config
from app.db import models as db_models
from app.services.anchor_adapter import get_anchor_adapter

GENESIS_HASH = "GENESIS"


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def compute_record_hash(
    previous_record_hash: str,
    timestamp_hashed: str,
    schema_version: str,
    evidence_digest: str,
) -> str:
    """Hash one ledger record. Shared by registration and verification so the
    recomputation path cannot drift from the write path."""
    return _sha256_hex(
        _canonical_json(
            {
                "previous_record_hash": previous_record_hash,
                "timestamp_hashed": timestamp_hashed,
                "schema_version": schema_version,
                "evidence_digest": evidence_digest,
                "record_type": "evidence_ledger",
            }
        )
    )


def compute_chain_root(record_hash: str, previous_record_hash: str) -> str:
    """Cumulative chain tip after appending ``record_hash``."""
    return _sha256_hex(
        _canonical_json(
            {
                "record_hash": record_hash,
                "previous_record_hash": previous_record_hash,
            }
        )
    )


class EvidenceAnchorService:
    """Service for registering evidence packages and verifying integrity."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register_evidence_package(
        self,
        payload: dict[str, Any],
        evidence_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict) or not payload:
            raise ValueError("A non-empty evidence payload is required.")

        normalized_id = evidence_id or payload.get("evidence_id") or str(uuid.uuid4())
        package_payload = json.loads(_canonical_json(payload))
        evidence_hash = _sha256_hex(_canonical_json(package_payload))
        evidence_digest = evidence_hash

        existing_package = (
            self.db.query(db_models.EvidencePackage)
            .filter(db_models.EvidencePackage.evidence_hash == evidence_hash)
            .first()
        )
        if existing_package is not None:
            # Duplicate submission: return the existing registration verbatim.
            # Evidence registration is idempotent — re-submitting the same
            # package must never create a second ledger record.
            return {
                "evidence_id": existing_package.evidence_id,
                "evidence_hash": existing_package.evidence_hash,
                "local_chain_root": existing_package.local_chain_root,
                "anchor_status": existing_package.anchor_status,
                "local_chain_status": existing_package.local_chain_status,
                "status": existing_package.status,
                "duplicate": True,
            }

        package = db_models.EvidencePackage(
            evidence_id=normalized_id,
            evidence_hash=evidence_hash,
            evidence_digest=evidence_digest,
            schema_version=config.EVIDENCE_SCHEMA_VERSION,
            package_format="technical-integrity-evidence-package",
            package_payload=_canonical_json(package_payload),
            status="registered",
            local_chain_status="pending",
            anchor_status="unavailable" if not config.BLOCKCHAIN_ANCHORING_ENABLED else "pending",
            blockchain_network=config.BLOCKCHAIN_NETWORK if config.BLOCKCHAIN_ANCHORING_ENABLED else None,
            contract_address=config.BLOCKCHAIN_CONTRACT_ADDRESS if config.BLOCKCHAIN_ANCHORING_ENABLED else None,
        )

        self.db.add(package)
        self.db.flush()

        previous_record_hash = self._get_latest_chain_root()
        timestamp_hashed = _utc_now().isoformat()

        record_hash = compute_record_hash(
            previous_record_hash=previous_record_hash,
            timestamp_hashed=timestamp_hashed,
            schema_version=config.EVIDENCE_SCHEMA_VERSION,
            evidence_digest=evidence_digest,
        )
        chain_root_hash = compute_chain_root(record_hash, previous_record_hash)

        ledger_record = db_models.EvidenceLedgerRecord(
            evidence_id=normalized_id,
            record_hash=record_hash,
            previous_record_hash=previous_record_hash,
            # The string that was hashed, stored verbatim: verification
            # recomputes over this exact value (immune to DB datetime
            # normalization losing the UTC offset).
            timestamp_hashed=timestamp_hashed,
            timestamp=_utc_now(),
            schema_version=config.EVIDENCE_SCHEMA_VERSION,
            evidence_digest=evidence_digest,
            chain_root_hash=chain_root_hash,
        )
        self.db.add(ledger_record)

        package.local_chain_root = chain_root_hash
        package.local_chain_status = "verified"
        package.status = "registered"

        if config.BLOCKCHAIN_ANCHORING_ENABLED:
            anchor_result = get_anchor_adapter().anchor_root(chain_root_hash, normalized_id)
            package.blockchain_network = anchor_result.get("network") or package.blockchain_network
            package.contract_address = anchor_result.get("contract_address") or package.contract_address
            package.anchor_tx_hash = anchor_result.get("tx_hash")
            package.anchor_block_number = anchor_result.get("block_number")
            package.anchor_timestamp = anchor_result.get("anchor_timestamp")
            package.anchor_status = anchor_result.get("status", "unavailable")
            package.failure_reason = anchor_result.get("failure_reason")
            self.db.add(
                db_models.EvidenceAnchor(
                    evidence_id=normalized_id,
                    root_hash=chain_root_hash,
                    blockchain_network=anchor_result.get("network") or config.BLOCKCHAIN_NETWORK,
                    contract_address=anchor_result.get("contract_address") or config.BLOCKCHAIN_CONTRACT_ADDRESS,
                    tx_hash=anchor_result.get("tx_hash"),
                    block_number=anchor_result.get("block_number"),
                    anchor_timestamp=anchor_result.get("anchor_timestamp"),
                    status=anchor_result.get("status", "unavailable"),
                    failure_reason=anchor_result.get("failure_reason"),
                )
            )
        else:
            package.anchor_status = "unavailable"
            package.blockchain_network = None
            package.contract_address = None
            package.failure_reason = (
                "Public blockchain anchoring is disabled in config; local evidence ledger remains available."
            )

        self.db.commit()
        self.db.refresh(package)

        return {
            "evidence_id": package.evidence_id,
            "evidence_hash": package.evidence_hash,
            "local_chain_root": package.local_chain_root,
            "anchor_status": package.anchor_status,
            "local_chain_status": package.local_chain_status,
            "status": package.status,
        }

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------
    def verify_evidence_package(self, evidence_id: str) -> dict[str, Any]:
        package = (
            self.db.query(db_models.EvidencePackage)
            .filter(db_models.EvidencePackage.evidence_id == evidence_id)
            .first()
        )
        if package is None:
            raise ValueError(f"Evidence package '{evidence_id}' was not found.")

        recomputed_hash = _sha256_hex(package.package_payload)
        evidence_hash_integrity = recomputed_hash == package.evidence_hash

        records = (
            self.db.query(db_models.EvidenceLedgerRecord)
            .filter(db_models.EvidenceLedgerRecord.evidence_id == evidence_id)
            .order_by(db_models.EvidenceLedgerRecord.record_id.asc())
            .all()
        )

        local_chain_integrity = True
        first_expected_previous = self._expected_previous_for_first_record(records)
        expected_previous_hash = first_expected_previous
        expected_chain_root: Optional[str] = None

        for record in records:
            expected_record_hash = compute_record_hash(
                previous_record_hash=expected_previous_hash,
                timestamp_hashed=record.timestamp_hashed or record.timestamp.isoformat(),
                schema_version=record.schema_version,
                evidence_digest=record.evidence_digest,
            )
            expected_chain_root = compute_chain_root(expected_record_hash, expected_previous_hash)

            if record.previous_record_hash != expected_previous_hash:
                local_chain_integrity = False
            if record.record_hash != expected_record_hash:
                local_chain_integrity = False
            if record.chain_root_hash != expected_chain_root:
                local_chain_integrity = False

            expected_previous_hash = expected_chain_root

        if expected_chain_root is None or package.local_chain_root != expected_chain_root:
            local_chain_integrity = False

        latest_anchor = (
            self.db.query(db_models.EvidenceAnchor)
            .filter(db_models.EvidenceAnchor.evidence_id == evidence_id)
            .order_by(db_models.EvidenceAnchor.anchor_id.desc())
            .first()
        )

        # Anchor consistency requires BOTH: an anchor that actually succeeded
        # on-chain AND its recorded root matching this package's chain root.
        # A failed submission also persists an EvidenceAnchor row (with its
        # failure_reason) but must never count as a confirmed anchor.
        public_anchor_consistent = bool(
            latest_anchor is not None
            and latest_anchor.status == "anchored"
            and latest_anchor.root_hash == package.local_chain_root
        )

        return {
            "evidence_id": evidence_id,
            "evidence_hash_integrity": evidence_hash_integrity,
            "local_chain_integrity": local_chain_integrity,
            "public_anchor_consistent": public_anchor_consistent,
            "evidence_hash": package.evidence_hash,
            "local_chain_root": package.local_chain_root,
            "anchor_status": package.anchor_status,
            "blockchain_network": package.blockchain_network,
            "contract_address": package.contract_address,
            "tx_hash": package.anchor_tx_hash,
            "anchor_timestamp": package.anchor_timestamp.isoformat() if package.anchor_timestamp else None,
            "failure_reason": package.failure_reason,
            "ledger_record_count": len(records),
            "first_record_previous_hash": first_expected_previous,
            "full_chain_integrity": self.verify_full_chain()["integrity"],
        }

    def verify_full_chain(self) -> dict[str, Any]:
        """Independently walk the ENTIRE ledger from GENESIS.

        This is the primitive an auditor (or the CLI verifier) runs: it trusts
        only the append-only record contents, recomputing every hash link.
        """
        records = (
            self.db.query(db_models.EvidenceLedgerRecord)
            .order_by(db_models.EvidenceLedgerRecord.record_id.asc())
            .all()
        )

        expected_previous = GENESIS_HASH
        broken_at: Optional[int] = None
        reason: Optional[str] = None

        for record in records:
            expected_record_hash = compute_record_hash(
                previous_record_hash=expected_previous,
                timestamp_hashed=record.timestamp_hashed or record.timestamp.isoformat(),
                schema_version=record.schema_version,
                evidence_digest=record.evidence_digest,
            )
            expected_root = compute_chain_root(expected_record_hash, expected_previous)

            if record.previous_record_hash != expected_previous:
                broken_at = record.record_id
                reason = f"record {record.record_id} links to {record.previous_record_hash[:16]}… but expected {expected_previous[:16]}…"
                break
            if record.record_hash != expected_record_hash:
                broken_at = record.record_id
                reason = f"record {record.record_id} hash mismatch (payload altered or hash forged)"
                break
            if record.chain_root_hash != expected_root:
                broken_at = record.record_id
                reason = f"record {record.record_id} chain root mismatch"
                break

            expected_previous = expected_root

        intact = broken_at is None
        return {
            "integrity": intact,
            "record_count": len(records),
            "chain_tip": expected_previous if intact else None,
            "broken_at_record": broken_at,
            "reason": reason if not intact else None,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _get_latest_chain_root(self) -> str:
        latest_record = (
            self.db.query(db_models.EvidenceLedgerRecord)
            .order_by(db_models.EvidenceLedgerRecord.record_id.desc())
            .first()
        )
        return latest_record.chain_root_hash if latest_record else GENESIS_HASH

    def _expected_previous_for_first_record(self, records: List[db_models.EvidenceLedgerRecord]) -> str:
        """What the package's first record SHOULD link to.

        If the package's first record is also the ledger's first record, it
        links to GENESIS. Otherwise it links to the chain root of the record
        immediately preceding it in the global ledger (multi-package chain).
        """
        if not records:
            return GENESIS_HASH
        first = records[0]
        predecessor = (
            self.db.query(db_models.EvidenceLedgerRecord)
            .filter(db_models.EvidenceLedgerRecord.record_id < first.record_id)
            .order_by(db_models.EvidenceLedgerRecord.record_id.desc())
            .first()
        )
        return predecessor.chain_root_hash if predecessor is not None else GENESIS_HASH
