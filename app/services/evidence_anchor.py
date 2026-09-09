"""Evidence anchoring and verification for finalized forensic packages.

This module maintains a local append-only integrity ledger for finalized
Phase 7 forensic evidence packages and provides deterministic verification.
The public blockchain layer is intentionally isolated behind this service so
it can be enabled or disabled without changing the rest of the application.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

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


class EvidenceAnchorService:
    """Service for registering Phase 7 evidence packages and verifying integrity."""

    def __init__(self, db: Session):
        self.db = db

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
            return {
                "evidence_id": existing_package.evidence_id,
                "evidence_hash": existing_package.evidence_hash,
                "local_chain_root": existing_package.local_chain_root,
                "anchor_status": existing_package.anchor_status,
                "local_chain_status": existing_package.local_chain_status,
                "status": existing_package.status,
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
        now = _utc_now()
        timestamp = now.isoformat()

        record_hash = _sha256_hex(
            _canonical_json(
                {
                    "previous_record_hash": previous_record_hash,
                    "timestamp": timestamp,
                    "schema_version": config.EVIDENCE_SCHEMA_VERSION,
                    "evidence_digest": evidence_digest,
                }
            )
        )
        chain_root_hash = _sha256_hex(
            _canonical_json(
                {
                    "record_hash": record_hash,
                    "previous_record_hash": previous_record_hash,
                }
            )
        )

        ledger_record = db_models.EvidenceLedgerRecord(
            evidence_id=normalized_id,
            record_hash=record_hash,
            previous_record_hash=previous_record_hash,
            timestamp=now,
            schema_version=config.EVIDENCE_SCHEMA_VERSION,
            evidence_digest=evidence_digest,
            chain_root_hash=chain_root_hash,
        )
        self.db.add(ledger_record)

        package.local_chain_root = chain_root_hash
        package.local_chain_status = "verified"
        package.status = "registered"

        if config.BLOCKCHAIN_ANCHORING_ENABLED:
            adapter = get_anchor_adapter()
            anchor_result = adapter.anchor_root(chain_root_hash, normalized_id)
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

        ledger_records = (
            self.db.query(db_models.EvidenceLedgerRecord)
            .filter(db_models.EvidenceLedgerRecord.evidence_id == evidence_id)
            .order_by(db_models.EvidenceLedgerRecord.record_id.asc())
            .all()
        )

        local_chain_integrity = True
        expected_previous_hash = GENESIS_HASH
        expected_chain_root = None

        for record in ledger_records:
            expected_record_hash = _sha256_hex(
                _canonical_json(
                    {
                        "previous_record_hash": expected_previous_hash,
                        "timestamp": record.timestamp.isoformat(),
                        "schema_version": record.schema_version,
                        "evidence_digest": record.evidence_digest,
                    }
                )
            )
            expected_chain_root = _sha256_hex(
                _canonical_json(
                    {
                        "record_hash": expected_record_hash,
                        "previous_record_hash": expected_previous_hash,
                    }
                )
            )

            if record.record_hash != expected_record_hash:
                local_chain_integrity = False
            if record.chain_root_hash != expected_chain_root:
                local_chain_integrity = False
            if record.previous_record_hash != expected_previous_hash:
                local_chain_integrity = False

            expected_previous_hash = expected_chain_root

        local_chain_integrity = local_chain_integrity and (
            package.local_chain_root == expected_chain_root
        )

        latest_anchor = (
            self.db.query(db_models.EvidenceAnchor)
            .filter(db_models.EvidenceAnchor.evidence_id == evidence_id)
            .order_by(db_models.EvidenceAnchor.anchor_id.desc())
            .first()
        )

        public_anchor_consistent = False
        if latest_anchor is not None:
            public_anchor_consistent = latest_anchor.root_hash == package.local_chain_root

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
            "ledger_record_count": len(ledger_records),
        }

    def _get_latest_chain_root(self) -> str:
        latest_record = (
            self.db.query(db_models.EvidenceLedgerRecord)
            .order_by(db_models.EvidenceLedgerRecord.record_id.desc())
            .first()
        )
        return latest_record.chain_root_hash if latest_record else GENESIS_HASH
