"""Offline anchor queue (Phase 10).

PROBLEM
  SatyaVoice targets rural/offline deployments. A device may finalize an
  evidence package while the network (or the RPC endpoint) is unreachable. The
  design requires that such evidence is *queued*, not dropped, and later
  anchored to the public chain when connectivity returns.

LIFECYCLE (mirrors the design document's states, additionally mapping the
legacy adapter vocabulary onto them):

    OFFLINE    — created while offline / anchoring disabled; awaiting submission.
    PENDING    — a transaction has been submitted, awaiting confirmation.
    CONFIRMED  — mined and confirmed (status=1); tx hash + block recorded.
    FAILED     — the transaction or RPC call failed; retained for operator retry.

  The adapter reports its own vocabulary ("anchored", "unavailable", "failed",
  "pending"); :func:`_status_from_adapter` maps those to the queue states above
  so the two never drift.

GUARANTEES
  - A failed anchor is never discarded — it stays with ``status='FAILED'`` and a
    ``last_error`` reason so an operator can retry (:func:`retry_entry`).
  - The queue is append-only per root (unique on ``root_hash``), so a root is
    never enqueued twice.
  - Every transition bumps ``attempts`` and ``updated_at`` for auditability.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app import config
from app.db import models as db_models

logger = logging.getLogger("satyavoice.anchor_queue")

# Canonical queue states.
OFFLINE = "OFFLINE"
PENDING = "PENDING"
CONFIRMED = "CONFIRMED"
FAILED = "FAILED"
# Non-retryable terminal state: the adapter/contract rejected the anchor for a
# reason that a retry cannot fix (contract revert, invalid root). The entry is
# retained for operator inspection — never silently dropped.
PERMANENTLY_FAILED = "PERMANENTLY_FAILED"

ALL_STATES = (OFFLINE, PENDING, CONFIRMED, FAILED, PERMANENTLY_FAILED)

# Exponential backoff: base seconds ** (attempts-1), capped. After the cap the
# entry stays FAILED but is only retried by an explicit operator action.
_BACKOFF_BASE_SECONDS = 60.0
_BACKOFF_MAX_SECONDS = 3600.0  # 1 hour
_MAX_AUTO_ATTEMPTS = 6

# Substrings that identify a PERMANENT (non-retryable) failure: the chain or the
# contract rejected the submission for a reason a retry cannot fix (revert,
# malformed/zero root, invalid evidence id, wrong chain). Everything else is
# treated as transient and remains retryable — a transient RPC timeout and an
# unrecognised adapter error both deserve a bounded retry, and the exponential
# backoff plus _MAX_AUTO_ATTEMPTS bound the damage of retrying a bad entry.
_PERMANENT_ERROR_MARKERS = (
    "revert",
    "invalid",
    "not permitted",
    "input error",
    "zero root hash",
    "chain id mismatch",
    "already anchored",
)


def _is_retryable_failure(reason: str | None) -> bool:
    """Classify a failure reason as retryable (transient) or permanent."""
    if not reason:
        return True  # unknown cause: give it the benefit of the doubt once
    lowered = reason.lower()
    return not any(marker in lowered for marker in _PERMANENT_ERROR_MARKERS)


def _status_from_adapter(anchor_result: dict[str, Any]) -> str:
    """Map an adapter result status onto a queue state."""
    status = (anchor_result or {}).get("status")
    if status == "anchored":
        return CONFIRMED
    if status in {"pending"}:
        return PENDING
    if status in {"failed"}:
        if not _is_retryable_failure((anchor_result or {}).get("failure_reason")):
            return PERMANENTLY_FAILED
        return FAILED
    if status == "dry_run":
        # A DRY_RUN "anchor" committed nothing on-chain; the entry stays queued
        # for a real submission and the simulated tx hash is NOT recorded.
        return OFFLINE
    # "unavailable" or anything unexpected: still queued, awaiting a retry.
    return OFFLINE


def _next_retry_time(attempts: int) -> datetime:
    """Exponential backoff deadline after *attempts* failed attempts."""
    delay = min(_BACKOFF_BASE_SECONDS * (2 ** max(0, attempts - 1)), _BACKOFF_MAX_SECONDS)
    return datetime.now(timezone.utc) + timedelta(seconds=delay)


def _apply_result(entry: db_models.AnchorQueueEntry, anchor_result: dict[str, Any]) -> None:
    """Copy an adapter result onto a queue entry in place."""
    status = _status_from_adapter(anchor_result)
    entry.status = status
    entry.attempts = (entry.attempts or 0) + 1
    entry.last_error = anchor_result.get("failure_reason")
    if status == CONFIRMED:
        # Only a CONFIRMED result records transaction metadata; a DRY_RUN
        # simulated tx hash must never be persisted as if it were real.
        entry.tx_hash = anchor_result.get("tx_hash")
        entry.block_number = anchor_result.get("block_number")
        ts = anchor_result.get("anchor_timestamp")
        if ts is not None and not isinstance(ts, datetime):
            try:
                ts = datetime.fromisoformat(str(ts))
            except (ValueError, TypeError):
                ts = None
        entry.anchor_timestamp = ts
        entry.next_retry_at = None
        entry.retryable = False  # terminal success: nothing left to retry
    elif status in (FAILED, PERMANENTLY_FAILED):
        entry.next_retry_at = (
            _next_retry_time(entry.attempts)
            if status == FAILED and entry.attempts < _MAX_AUTO_ATTEMPTS
            else None
        )
        if status == PERMANENTLY_FAILED or entry.attempts >= _MAX_AUTO_ATTEMPTS:
            entry.retryable = False
    entry.blockchain_network = anchor_result.get("network") or entry.blockchain_network
    entry.contract_address = anchor_result.get("contract_address") or entry.contract_address
    entry.updated_at = datetime.now(timezone.utc).replace(microsecond=0)


def _idempotency_key(root_hash: str, evidence_id: str) -> str:
    """Stable idempotency key for one logical anchor submission."""
    return hashlib.sha256(f"{root_hash}|{evidence_id}".encode("utf-8")).hexdigest()


def enqueue(
    db: Session,
    evidence_id: str,
    root_hash: str,
    evidence_id_bytes32: str,
) -> db_models.AnchorQueueEntry:
    """Create an OFFLINE queue entry for a root (idempotent per root)."""
    existing = (
        db.query(db_models.AnchorQueueEntry)
        .filter(db_models.AnchorQueueEntry.root_hash == root_hash)
        .first()
    )
    if existing is not None:
        return existing
    entry = db_models.AnchorQueueEntry(
        evidence_id=evidence_id,
        root_hash=root_hash,
        evidence_id_bytes32=evidence_id_bytes32,
        blockchain_network=config.BLOCKCHAIN_NETWORK,
        contract_address=config.BLOCKCHAIN_CONTRACT_ADDRESS or None,
        status=OFFLINE,
        attempts=0,
        idempotency_key=_idempotency_key(root_hash, evidence_id),
    )
    db.add(entry)
    db.flush()
    return entry


def record_anchor_result(
    db: Session,
    evidence_id: str,
    root_hash: str,
    anchor_result: dict[str, Any],
) -> dict[str, Any]:
    """Upsert the queue entry for a root and apply an adapter result.

    Returns a small status summary safe to embed in an API response.
    """
    entry = enqueue(db, evidence_id, root_hash, _bytes32_for(db, evidence_id, root_hash))
    _apply_result(entry, anchor_result)
    db.flush()
    return {
        "queue_status": entry.status,
        "attempts": entry.attempts,
        "tx_hash": entry.tx_hash,
        "block_number": entry.block_number,
        "last_error": entry.last_error,
        "retryable": entry.retryable if entry.retryable is not None else True,
        "next_retry_at": entry.next_retry_at.isoformat() if entry.next_retry_at else None,
    }


def _bytes32_for(db: Session, evidence_id: str, root_hash: str) -> str:
    """Best-effort resolution of the bytes32 id (falls back to stored value)."""
    entry = (
        db.query(db_models.AnchorQueueEntry)
        .filter(db_models.AnchorQueueEntry.root_hash == root_hash)
        .first()
    )
    if entry is not None:
        return entry.evidence_id_bytes32
    pkg = (
        db.query(db_models.EvidenceMerklePackage)
        .filter(db_models.EvidenceMerklePackage.evidence_id == evidence_id)
        .first()
    )
    if pkg is not None:
        return pkg.evidence_id_bytes32
    from app.services.anchor_adapter import evidence_id_to_bytes32

    return evidence_id_to_bytes32(evidence_id)


def list_queue(db: Session, status: str | None = None) -> list[dict[str, Any]]:
    """Return queue entries, optionally filtered by status."""
    query = db.query(db_models.AnchorQueueEntry).order_by(
        db_models.AnchorQueueEntry.created_at.asc()
    )
    if status:
        query = query.filter(db_models.AnchorQueueEntry.status == status)
    return [_serialize(e) for e in query.all()]


def pending_entries(db: Session) -> list[db_models.AnchorQueueEntry]:
    """Entries that still need submission (OFFLINE, or FAILED whose backoff has
    elapsed). PERMANENTLY_FAILED entries are never auto-retried."""
    now = datetime.now(timezone.utc)
    due: list[db_models.AnchorQueueEntry] = []
    for entry in (
        db.query(db_models.AnchorQueueEntry)
        .filter(db_models.AnchorQueueEntry.status.in_((OFFLINE, FAILED)))
        .order_by(db_models.AnchorQueueEntry.created_at.asc())
        .all()
    ):
        if not entry.retryable:
            continue
        if entry.next_retry_at is not None:
            retry_at = entry.next_retry_at
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            if retry_at > now:
                continue  # still backing off
        due.append(entry)
    return due


def _already_anchored_elsewhere(adapter: Any, entry: db_models.AnchorQueueEntry) -> dict[str, Any] | None:
    """Pre-submit idempotency probe (Phase 11).

    Before resubmitting, ask the chain whether this root is already anchored.
    If it is — e.g. a client timeout left the first transaction mined but the
    result was never recorded — return an 'anchored' result so the entry is
    confirmed WITHOUT a second, contradicting transaction.
    """
    try:
        check = adapter.verify_evidence(entry.root_hash, entry.evidence_id)
    except Exception:  # pragma: no cover - defensive
        return None
    if isinstance(check, dict) and check.get("anchored") is True:
        return {
            "status": "anchored",
            "network": check.get("network") or entry.blockchain_network,
            "contract_address": entry.contract_address,
            # The first submission's tx hash is not locally known; honesty
            # beats invention — the receipt's block/timestamp stay None.
            "tx_hash": check.get("tx_hash"),
            "block_number": None,
            "anchor_timestamp": None,
            "failure_reason": None,
        }
    return None


def flush_queue(db: Session, limit: int = 25) -> dict[str, Any]:
    """Attempt to anchor every pending entry; called on reconnect.

    Never raises. Each entry is submitted through the configured adapter and its
    state updated. ``limit`` bounds the work per flush so a large backlog does
    not block the caller.
    """
    from app.services.anchor_adapter import get_anchor_adapter

    processed: list[dict[str, Any]] = []
    entries = pending_entries(db)[:limit]
    adapter = get_anchor_adapter()
    for entry in entries:
        # Phase 11: never resubmit a root that is already on-chain (ambiguous
        # timeout protection). A confirmed probe resolves the entry directly.
        precheck = _already_anchored_elsewhere(adapter, entry)
        if precheck is not None:
            _apply_result(entry, precheck)
            processed.append(_serialize(entry))
            continue
        try:
            result = adapter.anchor_evidence(entry.root_hash, entry.evidence_id)
        except Exception as exc:  # pragma: no cover - adapter never raises
            result = {
                "status": "failed",
                "failure_reason": f"Adapter error: {type(exc).__name__}",
                "tx_hash": None,
                "block_number": None,
                "anchor_timestamp": None,
            }
        _apply_result(entry, result)
        processed.append(_serialize(entry))
    try:
        db.commit()
    except Exception:  # pragma: no cover - defensive
        db.rollback()
    return {
        "processed": len(processed),
        "entries": processed,
        "remaining": len(pending_entries(db)),
    }


def retry_entry(db: Session, root_hash: str) -> dict[str, Any]:
    """Retry a single failed/offline entry by root hash.

    Raises ``KeyError`` if the root is not queued.
    """
    from app.services.anchor_adapter import get_anchor_adapter

    entry = (
        db.query(db_models.AnchorQueueEntry)
        .filter(db_models.AnchorQueueEntry.root_hash == root_hash)
        .first()
    )
    if entry is None:
        raise KeyError(f"Root '{root_hash}' is not in the anchor queue.")
    if entry.status == PERMANENTLY_FAILED or not entry.retryable:
        # Operator-visible refusal: this anchor failed for a non-retryable
        # reason; resubmitting cannot succeed and would double-annotate logs.
        return _serialize(entry)

    adapter = get_anchor_adapter()
    # Phase 11 idempotency: a retry first checks whether the root is already
    # anchored (e.g. the original submission actually mined) before sending a
    # second transaction.
    precheck = _already_anchored_elsewhere(adapter, entry)
    if precheck is not None:
        result = precheck
    else:
        try:
            result = adapter.anchor_evidence(entry.root_hash, entry.evidence_id)
        except Exception as exc:  # pragma: no cover - defensive
            result = {
                "status": "failed",
                "failure_reason": f"Adapter error: {type(exc).__name__}",
                "tx_hash": None,
                "block_number": None,
                "anchor_timestamp": None,
            }
    _apply_result(entry, result)
    db.commit()
    return _serialize(entry)


def _serialize(entry: db_models.AnchorQueueEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "evidence_id": entry.evidence_id,
        "root_hash": entry.root_hash,
        "evidence_id_bytes32": entry.evidence_id_bytes32,
        "status": entry.status,
        "attempts": entry.attempts,
        "idempotency_key": entry.idempotency_key,
        "retryable": entry.retryable if entry.retryable is not None else True,
        "next_retry_at": (
            entry.next_retry_at.isoformat() if entry.next_retry_at else None
        ),
        "tx_hash": entry.tx_hash,
        "block_number": entry.block_number,
        "anchor_timestamp": entry.anchor_timestamp.isoformat() if entry.anchor_timestamp else None,
        "blockchain_network": entry.blockchain_network,
        "contract_address": entry.contract_address,
        "last_error": entry.last_error,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
    }
