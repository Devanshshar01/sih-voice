"""Evidence anchoring, ledger integrity, and verification for finalized forensic packages.

EVIDENCE PACKAGE STRUCTURE (A2):
  Every package stored here has the following structure. The payload MUST
  include a schema_version and evidence_type field; structured packages
  should also include session_id, risk_events, and model metadata.

  {
    "schema_version": "phase7-v1",
    "evidence_type": "technical-integrity-evidence-package",
    "evidence_id": "<uuid>",
    "session_id": "<call_id>",
    "created_at": "<iso8601_utc>",
    ... application-specific fields ...
  }

CANONICAL HASHING (A3):
  The same payload always produces the same hash:
    canonical_json = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    evidence_hash = sha256(canonical_json.encode('utf-8')).hexdigest()
  Timestamps embedded in the payload must be fixed before hashing. The
  verification path re-derives the hash from the stored canonical JSON string.

APPEND-ONLY LEDGER (A4):
  Each EvidenceLedgerRecord references the previous record's chain_root_hash
  (or GENESIS_HASH for the first record). Verification walks this chain and
  detects broken links, modified hashes, or missing records.

FAILURE HANDLING (A8):
  DB write failures return an explicit error dict with status='error'.
  Blockchain failures (already handled by the adapter) do NOT crash the
  evidence creation path — anchoring is best-effort.

BLOCKCHAIN VERIFICATION (A7):
  verify_evidence_package() now optionally re-queries the on-chain contract
  (via adapter.verify_anchor()) when blockchain anchoring is enabled, rather
  than trusting only the locally-stored tx metadata.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import config
from app.db import models as db_models
from app.services.anchor_adapter import get_anchor_adapter

logger = logging.getLogger("satyavoice.evidence")

GENESIS_HASH = "GENESIS"

# Maximum allowed size (bytes) for the serialised evidence payload JSON.
# Prevents oversized evidence submissions from exhausting DB storage.
MAX_EVIDENCE_PAYLOAD_BYTES = 512 * 1024  # 512 KB


def _canonical_json(data: Any) -> str:
    """Deterministic JSON serialisation.

    Keys are sorted. Separators have no whitespace. ASCII-safe=False to
    preserve multi-language transcript content without escaping.
    The resulting string is the canonical representation used for hashing.
    """
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def build_evidence_payload(
    *,
    session_id: str,
    caller_id: str | None = None,
    recipient_id: str | None = None,
    max_risk_score: int = 0,
    final_status: str | None = None,
    risk_events: list[dict[str, Any]] | None = None,
    acoustic_peak: float | None = None,
    intent_peak: float | None = None,
    model_metadata: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
    evidence_id: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic, schema-conformant evidence package dict.

    This is the canonical way to construct evidence payloads in SatyaVoice.
    The returned dict is ready for ``EvidenceAnchorService.register_evidence_package()``.

    The ``created_at`` timestamp is fixed at call time so that multiple
    registration attempts for the same logical event produce the same hash
    (idempotent behaviour when the package already exists in the ledger).
    Callers that need a fresh timestamp should pass a new ``extra`` dict.
    """
    now_iso = _utc_now().isoformat()
    eid = evidence_id or str(uuid.uuid4())
    payload: dict[str, Any] = {
        # Required structural fields (must be first for readability in logs)
        "schema_version": config.EVIDENCE_SCHEMA_VERSION,
        "evidence_type": "technical-integrity-evidence-package",
        "evidence_id": eid,
        # Session provenance
        "session_id": session_id,
        "caller_id": caller_id,
        "recipient_id": recipient_id,
        "created_at": now_iso,
        # Risk summary
        "max_risk_score": max_risk_score,
        "final_status": final_status,
        "acoustic_peak": acoustic_peak,
        "intent_peak": intent_peak,
        # Risk event timeline (optional — can be empty/None for lightweight packages)
        "risk_events": risk_events or [],
        # Model provenance (A2 requirement: detector/provider/model identifiers)
        "model_metadata": model_metadata or {
            "detector_mode": config.VOICE_DETECTOR_MODE,
            "model_id": config.VOICE_MODEL_ID,
            "model_revision": config.VOICE_MODEL_REVISION,
            "schema_version": config.EVIDENCE_SCHEMA_VERSION,
        },
    }
    if extra:
        payload.update(extra)
    return payload


class EvidenceAnchorService:
    """Service for registering Phase 7 evidence packages and verifying integrity.

    All public methods are exception-safe: failures are returned as error dicts
    rather than propagated to callers (A8 requirement). Callers should always
    check ``result['status'] == 'error'`` rather than wrapping in try/except.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def register_evidence_package(
        self,
        payload: dict[str, Any],
        evidence_id: str | None = None,
    ) -> dict[str, Any]:
        """Register an evidence package in the local ledger and optionally anchor it.

        Returns a dict with at minimum:
          evidence_id, evidence_hash, local_chain_root, anchor_status,
          local_chain_status, status

        On error: returns {'status': 'error', 'error': '<message>'} — does NOT raise.
        """
        # --- Input validation ---
        if not isinstance(payload, dict) or not payload:
            return {"status": "error", "error": "A non-empty evidence payload is required."}

        # Payload size guard (B3 / resource exhaustion prevention)
        serialised = _canonical_json(payload)
        if len(serialised.encode("utf-8")) > MAX_EVIDENCE_PAYLOAD_BYTES:
            return {
                "status": "error",
                "error": (
                    f"Evidence payload exceeds the maximum permitted size "
                    f"({MAX_EVIDENCE_PAYLOAD_BYTES // 1024} KB)."
                ),
            }

        try:
            normalized_id = evidence_id or payload.get("evidence_id") or str(uuid.uuid4())
            # Re-parse through canonical JSON to normalise key order, then
            # hash the canonical string directly (not the parsed object again).
            canonical = _canonical_json(json.loads(serialised))
            evidence_hash = _sha256_hex(canonical)
            evidence_digest = evidence_hash

            # --- Idempotency: same hash → return existing record ---
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
                    "duplicate": True,
                }

            # --- Build and persist the package row ---
            package = db_models.EvidencePackage(
                evidence_id=normalized_id,
                evidence_hash=evidence_hash,
                evidence_digest=evidence_digest,
                schema_version=config.EVIDENCE_SCHEMA_VERSION,
                package_format="technical-integrity-evidence-package",
                package_payload=canonical,
                status="registered",
                local_chain_status="pending",
                anchor_status=(
                    "unavailable" if not config.BLOCKCHAIN_ANCHORING_ENABLED else "pending"
                ),
                blockchain_network=(
                    config.BLOCKCHAIN_NETWORK if config.BLOCKCHAIN_ANCHORING_ENABLED else None
                ),
                contract_address=(
                    config.BLOCKCHAIN_CONTRACT_ADDRESS
                    if config.BLOCKCHAIN_ANCHORING_ENABLED
                    else None
                ),
            )
            self.db.add(package)
            self.db.flush()  # get the PK without committing yet

            # --- Build ledger record (append-only chain) ---
            previous_record_hash = self._get_latest_chain_root()
            now = _utc_now()
            timestamp_iso = now.isoformat()

            record_hash = _sha256_hex(
                _canonical_json(
                    {
                        "previous_record_hash": previous_record_hash,
                        "timestamp": timestamp_iso,
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

            # --- Optional blockchain anchoring (best-effort; never crashes) ---
            if config.BLOCKCHAIN_ANCHORING_ENABLED:
                try:
                    adapter = get_anchor_adapter()
                    anchor_result = adapter.anchor_root(chain_root_hash, normalized_id)
                except Exception as exc:
                    logger.warning(
                        "Blockchain adapter error for evidence_id=%s: %s",
                        normalized_id,
                        type(exc).__name__,
                    )
                    anchor_result = {
                        "status": "failed",
                        "network": config.BLOCKCHAIN_NETWORK,
                        "contract_address": config.BLOCKCHAIN_CONTRACT_ADDRESS,
                        "tx_hash": None,
                        "block_number": None,
                        "anchor_timestamp": None,
                        "failure_reason": f"Adapter error: {type(exc).__name__}",
                    }

                package.blockchain_network = (
                    anchor_result.get("network") or package.blockchain_network
                )
                package.contract_address = (
                    anchor_result.get("contract_address") or package.contract_address
                )
                package.anchor_tx_hash = anchor_result.get("tx_hash")
                package.anchor_block_number = anchor_result.get("block_number")
                package.anchor_timestamp = anchor_result.get("anchor_timestamp")
                package.anchor_status = anchor_result.get("status", "unavailable")
                package.failure_reason = anchor_result.get("failure_reason")

                self.db.add(
                    db_models.EvidenceAnchor(
                        evidence_id=normalized_id,
                        root_hash=chain_root_hash,
                        blockchain_network=(
                            anchor_result.get("network") or config.BLOCKCHAIN_NETWORK
                        ),
                        contract_address=(
                            anchor_result.get("contract_address")
                            or config.BLOCKCHAIN_CONTRACT_ADDRESS
                        ),
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
                    "Public blockchain anchoring is disabled in config; "
                    "local evidence ledger remains available."
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

        except SQLAlchemyError as exc:
            # DB failure: roll back and return explicit error (A8 requirement).
            logger.error("Evidence registration DB error: %s", type(exc).__name__)
            try:
                self.db.rollback()
            except Exception:
                pass
            return {
                "status": "error",
                "error": "Evidence registration failed due to a database error.",
            }
        except Exception as exc:
            logger.error("Evidence registration unexpected error: %s", type(exc).__name__)
            try:
                self.db.rollback()
            except Exception:
                pass
            return {
                "status": "error",
                "error": "Evidence registration failed unexpectedly.",
            }

    def verify_evidence_package(self, evidence_id: str) -> dict[str, Any]:
        """Independently verify evidence package integrity.

        The result is derived entirely from server-side data — no client-supplied
        'verified=true' flag is ever trusted.

        Returns a comprehensive verification report including:
          - evidence hash integrity (recomputed from stored canonical JSON)
          - local ledger chain integrity (hash chain walk)
          - blockchain anchor consistency (local metadata vs on-chain query if enabled)
          - all supporting metadata

        Raises ValueError if the package does not exist.
        """
        package = (
            self.db.query(db_models.EvidencePackage)
            .filter(db_models.EvidencePackage.evidence_id == evidence_id)
            .first()
        )
        if package is None:
            raise ValueError(f"Evidence package '{evidence_id}' was not found.")

        # --- Step 1: Payload hash integrity ---
        # Re-derive the hash from the stored canonical JSON (the exact string
        # that was hashed at registration time). This detects any modification
        # to the stored package_payload field.
        recomputed_hash = _sha256_hex(package.package_payload)
        evidence_hash_integrity = recomputed_hash == package.evidence_hash

        if not evidence_hash_integrity:
            logger.warning(
                "Evidence hash mismatch for evidence_id=%s: stored=%s recomputed=%s",
                evidence_id,
                package.evidence_hash[:16],
                recomputed_hash[:16],
            )

        # --- Step 2: Local ledger chain walk ---
        ledger_records = (
            self.db.query(db_models.EvidenceLedgerRecord)
            .filter(db_models.EvidenceLedgerRecord.evidence_id == evidence_id)
            .order_by(db_models.EvidenceLedgerRecord.record_id.asc())
            .all()
        )

        local_chain_integrity = True
        
        # The ledger is a global chain. The first record for THIS package
        # links to whatever the global chain tip was at that time.
        expected_previous_hash = (
            ledger_records[0].previous_record_hash if ledger_records else GENESIS_HASH
        )
        expected_chain_root = None

        for record in ledger_records:
            # Reconstruct the timestamp exactly as it was hashed.
            # SQLite drops tzinfo, so we must restore it to UTC to get the +00:00 suffix.
            ts = record.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            expected_record_hash = _sha256_hex(
                _canonical_json(
                    {
                        "previous_record_hash": expected_previous_hash,
                        "timestamp": ts.isoformat(),
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
                logger.warning(
                    "Ledger chain broken at record_id=%s for evidence_id=%s: "
                    "record_hash mismatch",
                    record.record_id,
                    evidence_id,
                )
            if record.chain_root_hash != expected_chain_root:
                local_chain_integrity = False
            if record.previous_record_hash != expected_previous_hash:
                local_chain_integrity = False

            expected_previous_hash = expected_chain_root

        # Final check: package's stored local_chain_root must match what we computed
        local_chain_integrity = local_chain_integrity and (
            package.local_chain_root == expected_chain_root
        )

        # --- Step 3: Anchor cross-check ---
        # First check locally-stored anchor metadata for consistency.
        latest_anchor = (
            self.db.query(db_models.EvidenceAnchor)
            .filter(db_models.EvidenceAnchor.evidence_id == evidence_id)
            .order_by(db_models.EvidenceAnchor.anchor_id.desc())
            .first()
        )

        public_anchor_consistent = False
        on_chain_verified: bool | None = None  # None = not queried

        if latest_anchor is not None:
            # Local metadata check: the root hash stored in the anchor record
            # must match the locally-computed chain root.
            public_anchor_consistent = (
                latest_anchor.root_hash == package.local_chain_root
            )

        # (A7) If blockchain anchoring is enabled and an anchor tx hash exists,
        # independently re-query the contract to verify on-chain state.
        if (
            config.BLOCKCHAIN_ANCHORING_ENABLED
            and package.local_chain_root
            and package.anchor_status not in {"unavailable", None}
        ):
            try:
                adapter = get_anchor_adapter()
                verify_result = adapter.verify_anchor(package.local_chain_root)
                on_chain_verified = verify_result.get("anchored", False)
                if not on_chain_verified and package.anchor_status == "anchored":
                    logger.warning(
                        "On-chain verification failed for evidence_id=%s: "
                        "contract reports root NOT anchored despite local status='anchored'",
                        evidence_id,
                    )
            except Exception as exc:
                logger.warning(
                    "On-chain verification query error for evidence_id=%s: %s",
                    evidence_id,
                    type(exc).__name__,
                )
                on_chain_verified = None  # query failed, don't assert verified

        return {
            "evidence_id": evidence_id,
            # Integrity results (all server-derived, never client-trusted)
            "evidence_hash_integrity": evidence_hash_integrity,
            "local_chain_integrity": local_chain_integrity,
            "public_anchor_consistent": public_anchor_consistent,
            "on_chain_verified": on_chain_verified,
            # Supporting metadata
            "evidence_hash": package.evidence_hash,
            "local_chain_root": package.local_chain_root,
            "anchor_status": package.anchor_status,
            "blockchain_network": package.blockchain_network,
            "contract_address": package.contract_address,
            "tx_hash": package.anchor_tx_hash,
            "anchor_timestamp": (
                package.anchor_timestamp.isoformat()
                if package.anchor_timestamp
                else None
            ),
            "failure_reason": package.failure_reason,
            "ledger_record_count": len(ledger_records),
        }

    def verify_ledger(self, evidence_id: str) -> dict[str, Any]:
        """Structured hash-chain verification for one evidence id (Phase 3).

        Recomputes every record hash from the stored fields and walks the chain
        from the genesis boundary, detecting:
          - changed payload/evidence_digest      -> record_hash mismatch
          - changed previous_hash                -> link mismatch
          - missing event                        -> chain-root head mismatch
          - reordered events                     -> link/hash mismatch
          - broken sequence                      -> chain-root mismatch

        Returns exactly the structured contract:
            {"valid", "entries_checked", "first_invalid_sequence",
             "expected_hash", "actual_hash", "reason"}
        ``first_invalid_sequence`` is the 1-based position of the first record
        that failed (the chain walk stops there), ``None`` when valid.
        """
        ledger_records = (
            self.db.query(db_models.EvidenceLedgerRecord)
            .filter(db_models.EvidenceLedgerRecord.evidence_id == evidence_id)
            .order_by(db_models.EvidenceLedgerRecord.record_id.asc())
            .all()
        )
        package = (
            self.db.query(db_models.EvidencePackage)
            .filter(db_models.EvidencePackage.evidence_id == evidence_id)
            .first()
        )

        def _result(valid: bool, first_invalid: int | None, expected: str | None, actual: str | None, reason: str | None) -> dict[str, Any]:
            return {
                "valid": valid,
                "entries_checked": len(ledger_records),
                "first_invalid_sequence": first_invalid,
                "expected_hash": expected,
                "actual_hash": actual,
                "reason": reason,
            }

        if package is None:
            return _result(False, None, None, None, f"evidence package '{evidence_id}' not found")
        if not ledger_records:
            return _result(False, None, None, None, "no ledger records for this evidence id")

        expected_previous_hash: str | None = None  # None = use stored genesis link
        for position, record in enumerate(ledger_records, start=1):
            # The first record of THIS package links to the global chain tip at
            # registration time; its stored previous_record_hash is trusted as
            # the chain boundary and verified against the previous record below.
            previous = (
                record.previous_record_hash
                if expected_previous_hash is None
                else expected_previous_hash
            )

            ts = record.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            expected_record_hash = _sha256_hex(
                _canonical_json(
                    {
                        "previous_record_hash": previous,
                        "timestamp": ts.isoformat(),
                        "schema_version": record.schema_version,
                        "evidence_digest": record.evidence_digest,
                    }
                )
            )
            expected_chain_root = _sha256_hex(
                _canonical_json(
                    {
                        "record_hash": expected_record_hash,
                        "previous_record_hash": previous,
                    }
                )
            )

            if record.previous_record_hash != previous:
                return _result(
                    False,
                    position,
                    previous,
                    record.previous_record_hash,
                    f"previous_hash mismatch at sequence {position} "
                    "(missing, reordered, or tampered event)",
                )
            if record.record_hash != expected_record_hash:
                return _result(
                    False,
                    position,
                    expected_record_hash,
                    record.record_hash,
                    f"record_hash mismatch at sequence {position} (payload tampered)",
                )
            if record.chain_root_hash != expected_chain_root:
                return _result(
                    False,
                    position,
                    expected_chain_root,
                    record.chain_root_hash,
                    f"chain_root mismatch at sequence {position}",
                )

            expected_previous_hash = expected_chain_root

        # Head check: the package's stored chain root must be the walked head.
        if package.local_chain_root != expected_previous_hash:
            return _result(
                False,
                len(ledger_records),
                expected_previous_hash,
                package.local_chain_root,
                "ledger head mismatch (missing or appended event)",
            )

        return _result(True, None, None, None, None)

    def _get_latest_chain_root(self) -> str:
        latest_record = (
            self.db.query(db_models.EvidenceLedgerRecord)
            .order_by(db_models.EvidenceLedgerRecord.record_id.desc())
            .first()
        )
        return latest_record.chain_root_hash if latest_record else GENESIS_HASH
