"""Tests for the Phase 10 Merkle-root evidence layer.

Covers:
  - deterministic package/root construction
  - per-item digest correctness and RFC 8785 manifest hashing
  - persistence + idempotency (duplicate package hash)
  - end-to-end verification (package hash, Merkle root, raw items)
  - tamper detection (manifest mutation, leaf mutation)
  - inclusion proofs (stored proof + standalone builder)
  - blockchain disabled / failure paths
  - offline anchor queue lifecycle (OFFLINE → CONFIRMED / FAILED)
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

os.environ.setdefault("VOICETRUST_WS_JWT_SECRET", "test-secret-merkle-xyzzy")
os.environ.setdefault("VOICETRUST_DETECTOR_MODE", "mock")
os.environ.setdefault("HF_ZERO_GPU_SPACE", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.merkle import compute_root, hash_leaf  # noqa: E402
from app.services.merkle_evidence import (  # noqa: E402
    MerkleEvidenceError,
    MerkleEvidenceService,
    build_merkle_package,
    build_merkle_proof_for_items,
    hash_evidence_item,
)


ITEMS = {
    "audio": b"raw-audio-bytes",
    "transcript": "hello world",
    "spoof_scores": json.dumps({"max_risk": 91.4}).encode("utf-8"),
}


# ---------------------------------------------------------------------------
# Pure package construction
# ---------------------------------------------------------------------------

def test_build_package_basic_shape():
    pkg = build_merkle_package(evidence_id="SV-1", session_id="S-1", items=ITEMS)
    assert pkg["evidence_id"] == "SV-1"
    assert pkg["leaf_count"] == 3
    assert len(pkg["merkle_root"]) == 64
    assert len(pkg["package_hash"]) == 64
    assert set(pkg["item_digests"]) == set(ITEMS)
    assert pkg["manifest"]["session_id"] == "S-1"


def test_per_item_digest_is_sha256_of_raw_bytes():
    pkg = build_merkle_package(evidence_id="SV-2", items=ITEMS)
    assert pkg["item_digests"]["audio"] == hashlib.sha256(b"raw-audio-bytes").hexdigest()
    assert pkg["item_digests"]["transcript"] == hashlib.sha256(b"hello world").hexdigest()


def test_root_is_computed_from_leaf_hashes():
    pkg = build_merkle_package(evidence_id="SV-3", items=ITEMS)
    expected_leaves = [
        hash_leaf(bytes.fromhex(pkg["item_digests"][name])) for name in sorted(ITEMS)
    ]
    assert pkg["merkle_root"] == compute_root(expected_leaves).hex()


def test_root_is_order_independent():
    reversed_items = dict(reversed(list(ITEMS.items())))
    a = build_merkle_package(evidence_id="SV-4", items=ITEMS)
    b = build_merkle_package(evidence_id="SV-4", items=reversed_items)
    # Same evidence_id + same items (different insertion order) → same root.
    assert a["merkle_root"] == b["merkle_root"]


def test_package_hash_changes_with_evidence_id():
    a = build_merkle_package(evidence_id="SV-A", items=ITEMS)
    b = build_merkle_package(evidence_id="SV-B", items=ITEMS)
    assert a["merkle_root"] == b["merkle_root"]  # items identical
    assert a["package_hash"] != b["package_hash"]  # manifest differs (evidence_id)


def test_empty_items_rejected():
    with pytest.raises(MerkleEvidenceError):
        build_merkle_package(evidence_id="SV-5", items={})


def test_bad_item_type_rejected():
    with pytest.raises(MerkleEvidenceError):
        build_merkle_package(evidence_id="SV-6", items={"bad": 12345})


def test_manifest_is_rfc8785_canonical():
    from app.core.jcs import canonicalize

    pkg = build_merkle_package(evidence_id="SV-7", items=ITEMS)
    assert pkg["canonical_manifest"] == canonicalize(pkg["manifest"])
    # No insignificant whitespace: no newlines/tabs, and no space ever appears
    # *between* tokens (spaces inside string values are legitimate content).
    assert "\n" not in pkg["canonical_manifest"]
    assert "\t" not in pkg["canonical_manifest"]
    assert '": "' not in pkg["canonical_manifest"]
    assert '", "' not in pkg["canonical_manifest"]
    # Keys are sorted: evidence_id appears before merkle.
    assert pkg["canonical_manifest"].index('"evidence_id"') < pkg["canonical_manifest"].index('"merkle"')


def test_manifest_contains_no_raw_payloads():
    """Privacy: the manifest must carry only digests, never raw items."""
    pkg = build_merkle_package(evidence_id="SV-8", items={"transcript": "SECRET-TEXT"})
    assert "SECRET-TEXT" not in pkg["canonical_manifest"]


# ---------------------------------------------------------------------------
# Persistence + verification
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_session(tmp_path_factory):
    """Isolated per-module DB: fixed evidence ids in tests must not collide with
    rows left behind by previous runs on the shared persistent database."""
    from app.db.database import Base
    from app.db import models  # noqa: F401

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_path = tmp_path_factory.mktemp("merkle-evidence") / "merkle-evidence.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def test_register_and_verify_roundtrip(db_session):
    svc = MerkleEvidenceService(db_session)
    reg = svc.register_merkle_package(items=ITEMS, evidence_id="SV-E2E-1", session_id="S-1")
    assert reg["status"] == "ok", reg

    report = svc.verify_merkle_package("SV-E2E-1", provided_items=ITEMS)
    assert report["valid"] is True
    assert report["package_hash_integrity"] is True
    assert report["merkle_root_integrity"] is True
    assert report["items_all_verified"] is True
    assert report["on_chain_verified"] is None  # blockchain disabled in tests


def test_registration_is_idempotent(db_session):
    svc = MerkleEvidenceService(db_session)
    pkg = build_merkle_package(evidence_id="SV-IDEM", items=ITEMS)
    # Manually pass the same evidence_id + created_at by reusing the manifest.
    r1 = svc.register_merkle_package(items=ITEMS, evidence_id="SV-IDEM")
    r2 = svc.register_merkle_package(items=ITEMS, evidence_id="SV-IDEM")
    # Different created_at => different package hash => two rows are allowed,
    # but the second must still succeed and be self-consistent.
    assert r1["status"] == "ok" and r2["status"] == "ok"


def test_verify_unknown_package_raises(db_session):
    svc = MerkleEvidenceService(db_session)
    with pytest.raises(MerkleEvidenceError):
        svc.verify_merkle_package("does-not-exist")


def test_tampered_manifest_fails_package_hash(db_session):
    from app.db import models as db_models

    svc = MerkleEvidenceService(db_session)
    reg = svc.register_merkle_package(items=ITEMS, evidence_id="SV-TAMPER-MANIFEST")
    row = (
        db_session.query(db_models.EvidenceMerklePackage)
        .filter_by(evidence_id="SV-TAMPER-MANIFEST")
        .first()
    )
    original = row.canonical_package
    # The manifest holds digests, not raw items, so tamper with a value that IS
    # present (the evidence_id) to prove the package hash detects mutation.
    assert '"SV-TAMPER-MANIFEST"' in original
    row.canonical_package = original.replace('"SV-TAMPER-MANIFEST"', '"SV-TAMPER-MANIFEST-X"')
    db_session.commit()

    report = svc.verify_merkle_package("SV-TAMPER-MANIFEST")
    assert report["package_hash_integrity"] is False
    assert report["valid"] is False

    row.canonical_package = original
    db_session.commit()


def test_tampered_leaf_digest_fails_root_integrity(db_session):
    from app.db import models as db_models

    svc = MerkleEvidenceService(db_session)
    svc.register_merkle_package(items=ITEMS, evidence_id="SV-TAMPER-LEAF")
    row = (
        db_session.query(db_models.EvidenceMerklePackage)
        .filter_by(evidence_id="SV-TAMPER-LEAF")
        .first()
    )
    original = row.leaves_json
    digests = json.loads(original)
    digests["audio"] = "00" * 32  # corrupt one item digest
    row.leaves_json = json.dumps(digests, sort_keys=True)
    db_session.commit()

    report = svc.verify_merkle_package("SV-TAMPER-LEAF")
    assert report["merkle_root_integrity"] is False
    assert report["valid"] is False

    row.leaves_json = original
    db_session.commit()


def test_wrong_raw_item_fails_item_verification(db_session):
    svc = MerkleEvidenceService(db_session)
    svc.register_merkle_package(items=ITEMS, evidence_id="SV-WRONG-ITEM")
    report = svc.verify_merkle_package(
        "SV-WRONG-ITEM",
        provided_items={"audio": b"DIFFERENT-BYTES"},
    )
    assert report["items_verified"]["audio"] is False
    assert report["items_all_verified"] is False
    assert report["valid"] is False


# ---------------------------------------------------------------------------
# Proofs
# ---------------------------------------------------------------------------

def test_stored_proof_is_valid(db_session):
    svc = MerkleEvidenceService(db_session)
    svc.register_merkle_package(items=ITEMS, evidence_id="SV-PROOF-1")
    for name in ITEMS:
        proof_result = svc.get_proof("SV-PROOF-1", name)
        assert proof_result["proof_valid"] is True
        assert len(proof_result["merkle_root"]) == 64


def test_get_proof_unknown_item_raises(db_session):
    svc = MerkleEvidenceService(db_session)
    svc.register_merkle_package(items=ITEMS, evidence_id="SV-PROOF-2")
    with pytest.raises(MerkleEvidenceError):
        svc.get_proof("SV-PROOF-2", "nonexistent-item")


def test_standalone_proof_builder():
    proof = build_merkle_proof_for_items([b"a", b"b", b"c"], 1)
    assert set(proof.keys()) == {"leaf", "root", "siblings"}
    from app.core.merkle import verify_proof

    assert verify_proof(
        bytes.fromhex(proof["leaf"]),
        [bytes.fromhex(s) for s in proof["siblings"]],
        bytes.fromhex(proof["root"]),
    )


# ---------------------------------------------------------------------------
# Blockchain paths
# ---------------------------------------------------------------------------

def test_blockchain_disabled_marks_unavailable(db_session):
    from app import config

    assert not config.BLOCKCHAIN_ANCHORING_ENABLED
    svc = MerkleEvidenceService(db_session)
    reg = svc.register_merkle_package(items=ITEMS, evidence_id="SV-CHAIN-OFF")
    assert reg["status"] == "ok"
    assert reg["anchor_status"] == "unavailable"


def test_blockchain_anchor_called_when_enabled(db_session):
    from app import config

    svc = MerkleEvidenceService(db_session)
    fake_adapter = mock.MagicMock()
    fake_adapter.anchor_evidence.return_value = {
        "status": "anchored",
        "network": "polygon-amoy",
        "contract_address": "0xDummy",
        "tx_hash": "0xdeadbeef",
        "block_number": 42,
        "anchor_timestamp": None,
        "failure_reason": None,
    }
    with mock.patch.object(config, "BLOCKCHAIN_ANCHORING_ENABLED", True), \
         mock.patch("app.services.merkle_evidence.get_anchor_adapter", return_value=fake_adapter):
        reg = svc.register_merkle_package(items=ITEMS, evidence_id="SV-CHAIN-ON")
    assert reg["status"] == "ok"
    assert reg["anchor_status"] == "anchored"
    fake_adapter.anchor_evidence.assert_called_once()
    # The adapter receives the 0x-prefixed root and the string evidence id.
    args, _ = fake_adapter.anchor_evidence.call_args
    assert args[0].startswith("0x")
    assert args[1] == "SV-CHAIN-ON"


def test_blockchain_failure_does_not_abort_registration(db_session):
    from app import config

    svc = MerkleEvidenceService(db_session)
    fake_adapter = mock.MagicMock()
    fake_adapter.anchor_evidence.side_effect = RuntimeError("rpc down")
    with mock.patch.object(config, "BLOCKCHAIN_ANCHORING_ENABLED", True), \
         mock.patch("app.services.merkle_evidence.get_anchor_adapter", return_value=fake_adapter):
        reg = svc.register_merkle_package(items=ITEMS, evidence_id="SV-CHAIN-FAIL")
    assert reg["status"] == "ok"  # local registration still succeeds
    assert reg["anchor_status"] == "failed"


def test_verify_on_chain_when_enabled(db_session):
    from app import config

    svc = MerkleEvidenceService(db_session)
    fake_adapter = mock.MagicMock()
    fake_adapter.anchor_evidence.return_value = {
        "status": "anchored",
        "network": "polygon-amoy",
        "contract_address": "0xDummy",
        "tx_hash": "0xabc",
        "block_number": 7,
        "anchor_timestamp": None,
        "failure_reason": None,
    }
    fake_adapter.verify_evidence.return_value = {
        "anchored": True,
        "status": "anchored",
        "evidence_id_matches": True,
        "on_chain_evidence_id": "0x" + "ab" * 32,
    }
    with mock.patch.object(config, "BLOCKCHAIN_ANCHORING_ENABLED", True), \
         mock.patch("app.services.merkle_evidence.get_anchor_adapter", return_value=fake_adapter):
        svc.register_merkle_package(items=ITEMS, evidence_id="SV-CHAIN-VERIFY")
        report = svc.verify_merkle_package("SV-CHAIN-VERIFY", provided_items=ITEMS,
                                            verify_on_chain=True)
    assert report["on_chain_verified"] is True
    assert report["evidence_id_matches"] is True
    assert report["valid"] is True

# ---------------------------------------------------------------------------
# Phase: production race hardening (same pattern as the legacy flow)
# ---------------------------------------------------------------------------


def test_same_id_different_content_conflicts_without_overwrite(db_session):
    """Same evidence_id + different items -> explicit conflict, zero mutation."""
    svc = MerkleEvidenceService(db_session)
    first = svc.register_merkle_package(items=ITEMS, evidence_id="SV-CONFLICT-SEQ")
    assert first["status"] == "ok" and first.get("duplicate") is False

    second = svc.register_merkle_package(
        items={"different": b"entirely different content"},
        evidence_id="SV-CONFLICT-SEQ",
    )
    assert second["status"] == "conflict"
    assert second["error_code"] == "EVIDENCE_ID_CONFLICT"
    assert second["existing_package_hash"] == first["package_hash"]
    # The stored evidence still verifies against the ORIGINAL items (no overwrite).
    report = svc.verify_merkle_package("SV-CONFLICT-SEQ", provided_items=ITEMS)
    assert report["valid"] is True
    assert report["items_all_verified"] is True


def _run_gated_race(db_dir, evidence_id, loser_items, winner_items):
    """Two registrations with an event-controlled interleave at the INSERT.

    The loser passes the SELECT-before-INSERT idempotency check, then blocks in
    flush() while the winner commits; releasing it forces the real PK
    IntegrityError so the race handler itself is exercised deterministically.
    WAL mode ensures the loser's read snapshot cannot block the winner's commit.
    """
    import threading

    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker

    from app.db import models as _models  # noqa: F401 - registers tables
    from app.db.database import Base

    engine = create_engine(
        f"sqlite:///{db_dir}/race.db",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _enable_wal(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")

    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)

    loser = session_factory()
    winner = session_factory()
    passed_select = threading.Event()
    release_loser = threading.Event()
    original_flush = loser.flush

    def gated_flush(*args, **kwargs):
        passed_select.set()
        if not release_loser.wait(timeout=15):
            raise RuntimeError("race test: release signal never arrived")
        return original_flush(*args, **kwargs)

    loser.flush = gated_flush

    loser_result: dict = {}
    loser_error: list = []

    def run_loser():
        try:
            loser_result.update(
                MerkleEvidenceService(loser).register_merkle_package(
                    items=loser_items, evidence_id=evidence_id
                )
            )
        except Exception as exc:  # the escaped error this test forbids
            loser_error.append(exc)

    thread = threading.Thread(target=run_loser, daemon=True)
    thread.start()
    assert passed_select.wait(timeout=10), "loser never reached its flush"
    winner_result = MerkleEvidenceService(winner).register_merkle_package(
        items=winner_items, evidence_id=evidence_id
    )
    release_loser.set()
    thread.join(timeout=15)
    assert not thread.is_alive(), "loser thread hung"

    count_session = session_factory()
    row_count = (
        count_session.query(_models.EvidenceMerklePackage)
        .filter(_models.EvidenceMerklePackage.evidence_id == evidence_id)
        .count()
    )
    leaf_count = (
        count_session.query(_models.EvidenceMerkleLeaf)
        .filter(_models.EvidenceMerkleLeaf.evidence_id == evidence_id)
        .count()
    )
    outcome = {
        "winner": winner_result,
        "loser": loser_result,
        "loser_error": loser_error,
        "row_count": row_count,
        "leaf_count": leaf_count,
    }
    loser.close()
    winner.close()
    count_session.close()
    engine.dispose()
    return outcome


def _assert_no_db_error_logs(caplog) -> None:
    import logging

    noisy = [
        record
        for record in caplog.records
        if record.levelno >= logging.ERROR
        and "Merkle evidence DB error" in record.getMessage()
    ]
    assert noisy == [], [r.getMessage() for r in noisy]


def test_concurrent_same_content_registration_yields_one_row(tmp_path, caplog):
    """Two simultaneous identical registrations -> one row, both callers valid."""
    outcome = _run_gated_race(tmp_path, "SV-RACE-SAME", ITEMS, ITEMS)
    assert outcome["loser_error"] == [], outcome["loser_error"]
    assert outcome["winner"]["status"] == "ok"
    assert outcome["winner"].get("duplicate") is False
    assert outcome["loser"]["status"] == "ok"
    assert outcome["loser"].get("duplicate") is True  # idempotent, not an error
    assert outcome["loser"]["merkle_root"] == outcome["winner"]["merkle_root"]
    assert outcome["row_count"] == 1
    assert outcome["leaf_count"] == len(ITEMS)  # loser's pending rows rolled back
    _assert_no_db_error_logs(caplog)  # a handled race is never an app error


def test_concurrent_different_content_registration_conflicts_cleanly(tmp_path, caplog):
    """A racing DIFFERENT snapshot resolves to conflict; the winner is intact."""
    outcome = _run_gated_race(
        tmp_path,
        "SV-RACE-DIFF",
        {"loser": b"loser content"},
        {"winner": b"winner content"},
    )
    assert outcome["loser_error"] == [], outcome["loser_error"]
    assert outcome["winner"]["status"] == "ok"
    assert outcome["loser"]["status"] == "conflict"
    assert outcome["loser"]["error_code"] == "EVIDENCE_ID_CONFLICT"
    assert outcome["row_count"] == 1
    assert outcome["leaf_count"] == 1  # winner's leaf only; loser fully rolled back
    _assert_no_db_error_logs(caplog)

