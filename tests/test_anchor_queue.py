"""Tests for the Phase 10 offline anchor queue.

The queue is the mechanism that lets a disconnected (rural/edge) device finalize
evidence and anchor it later. These tests pin the lifecycle guarantees:

  - an enqueued root is OFFLINE and never dropped
  - a successful submission becomes CONFIRMED with tx/block recorded
  - a failed submission becomes FAILED and is retained for retry
  - flush_queue drains pending entries without raising
  - a root is never enqueued twice (unique on root_hash)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

import pytest

os.environ.setdefault("VOICETRUST_WS_JWT_SECRET", "test-secret-queue-xyzzy")
os.environ.setdefault("VOICETRUST_DETECTOR_MODE", "mock")
os.environ.setdefault("HF_ZERO_GPU_SPACE", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import anchor_queue  # noqa: E402
from app.services.merkle_evidence import MerkleEvidenceService  # noqa: E402


ITEMS = {"audio": b"queue-audio", "transcript": "queue transcript"}


@pytest.fixture(scope="module")
def db_session(tmp_path_factory):
    """Isolated per-module DB: fixed root hashes in tests must not collide with
    rows left behind by previous runs on the shared persistent database."""
    from app.db.database import Base
    from app.db import models  # noqa: F401

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_path = tmp_path_factory.mktemp("anchor-queue") / "anchor-queue.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _anchor_ok(root: str = "0x" + "aa" * 32):
    return {
        "status": "anchored",
        "network": "polygon-amoy",
        "contract_address": "0xDummy",
        "tx_hash": "0x" + "11" * 32,
        "block_number": 12345,
        "anchor_timestamp": None,
        "failure_reason": None,
    }


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------

def test_enqueue_creates_offline_entry(db_session):
    entry = anchor_queue.enqueue(db_session, "SV-Q-1", "0x" + "01" * 32, "0x" + "02" * 32)
    db_session.commit()
    assert entry.status == anchor_queue.OFFLINE
    assert entry.attempts == 0


def test_enqueue_is_idempotent_per_root(db_session):
    root = "0x" + "03" * 32
    e1 = anchor_queue.enqueue(db_session, "SV-Q-2", root, "0x" + "04" * 32)
    e2 = anchor_queue.enqueue(db_session, "SV-Q-2b", root, "0x" + "04" * 32)
    db_session.commit()
    assert e1.id == e2.id  # same row, not a duplicate
    assert len(anchor_queue.list_queue(db_session)) == len(
        {e["root_hash"] for e in anchor_queue.list_queue(db_session)}
    )


# ---------------------------------------------------------------------------
# Result application
# ---------------------------------------------------------------------------

def test_record_success_marks_confirmed(db_session):
    root = "0x" + "05" * 32
    summary = anchor_queue.record_anchor_result(db_session, "SV-Q-3", root, _anchor_ok(root))
    db_session.commit()
    assert summary["queue_status"] == anchor_queue.CONFIRMED
    assert summary["attempts"] == 1
    assert summary["tx_hash"] == "0x" + "11" * 32
    assert summary["block_number"] == 12345


def test_record_failure_marks_failed_and_is_retained(db_session):
    root = "0x" + "06" * 32
    failure = {
        "status": "failed",
        "network": "polygon-amoy",
        "contract_address": "0xDummy",
        "tx_hash": None,
        "block_number": None,
        "anchor_timestamp": None,
        "failure_reason": "RPC endpoint unreachable.",
    }
    summary = anchor_queue.record_anchor_result(db_session, "SV-Q-4", root, failure)
    db_session.commit()
    assert summary["queue_status"] == anchor_queue.FAILED
    assert summary["last_error"] == "RPC endpoint unreachable."

    # A failed entry must remain in the DB (never silently discarded).
    entry = (
        db_session.query(__import__("app.db.models", fromlist=["models"]).AnchorQueueEntry)
        .filter_by(root_hash=root)
        .first()
    )
    assert entry is not None


def test_unavailable_maps_to_offline(db_session):
    root = "0x" + "07" * 32
    summary = anchor_queue.record_anchor_result(
        db_session, "SV-Q-5", root,
        {"status": "unavailable", "failure_reason": "disabled", "tx_hash": None,
         "block_number": None, "anchor_timestamp": None},
    )
    db_session.commit()
    assert summary["queue_status"] == anchor_queue.OFFLINE


# ---------------------------------------------------------------------------
# Flush / retry
# ---------------------------------------------------------------------------

def test_flush_queue_confirms_pending(db_session):
    root = "0x" + "08" * 32
    anchor_queue.enqueue(db_session, "SV-Q-6", root, "0x" + "09" * 32)
    db_session.commit()

    fake_adapter = mock.MagicMock()
    fake_adapter.anchor_evidence.return_value = _anchor_ok(root)
    with mock.patch("app.services.anchor_adapter.get_anchor_adapter", return_value=fake_adapter):
        result = anchor_queue.flush_queue(db_session)

    assert result["processed"] >= 1
    confirmed = [e for e in result["entries"] if e["root_hash"] == root]
    assert confirmed and confirmed[0]["status"] == anchor_queue.CONFIRMED


def test_flush_queue_survives_adapter_error(db_session):
    root = "0x" + "0a" * 32
    anchor_queue.enqueue(db_session, "SV-Q-7", root, "0x" + "0b" * 32)
    db_session.commit()

    fake_adapter = mock.MagicMock()
    fake_adapter.anchor_evidence.side_effect = RuntimeError("boom")
    with mock.patch("app.services.anchor_adapter.get_anchor_adapter", return_value=fake_adapter):
        result = anchor_queue.flush_queue(db_session)  # must not raise

    failed = [e for e in result["entries"] if e["root_hash"] == root]
    assert failed and failed[0]["status"] == anchor_queue.FAILED


def test_retry_entry_unknown_root_raises(db_session):
    with pytest.raises(KeyError):
        anchor_queue.retry_entry(db_session, "0x" + "ff" * 32)


def test_retry_entry_retries_failed(db_session):
    root = "0x" + "0c" * 32
    anchor_queue.record_anchor_result(
        db_session, "SV-Q-8", root,
        {"status": "failed", "failure_reason": "temp", "tx_hash": None,
         "block_number": None, "anchor_timestamp": None},
    )
    db_session.commit()

    fake_adapter = mock.MagicMock()
    fake_adapter.anchor_evidence.return_value = _anchor_ok(root)
    with mock.patch("app.services.anchor_adapter.get_anchor_adapter", return_value=fake_adapter):
        entry = anchor_queue.retry_entry(db_session, root)

    assert entry["status"] == anchor_queue.CONFIRMED
    assert entry["attempts"] == 2  # first failure + successful retry


# ---------------------------------------------------------------------------
# Integration with the Merkle service
# ---------------------------------------------------------------------------

def test_merkle_registration_updates_queue_when_enabled(db_session):
    from app import config

    svc = MerkleEvidenceService(db_session)
    fake_adapter = mock.MagicMock()
    fake_adapter.anchor_evidence.return_value = _anchor_ok()
    with mock.patch.object(config, "BLOCKCHAIN_ANCHORING_ENABLED", True), \
         mock.patch("app.services.merkle_evidence.get_anchor_adapter", return_value=fake_adapter):
        reg = svc.register_merkle_package(items=ITEMS, evidence_id="SV-Q-INTEGRATION")

    assert reg["status"] == "ok"
    assert reg["queue_status"]["queue_status"] == anchor_queue.CONFIRMED
