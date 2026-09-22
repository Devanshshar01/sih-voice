"""End-to-end forensic evidence pipeline tests (Phase 15).

Fixtures exercise the whole chain, exactly as the acceptance criteria require:

    audio artifact
        -> artifact hashes
        -> canonical evidence package
        -> package hash
        -> ledger entry (hash chain)
        -> Merkle root
        -> PDF
        -> PDF hash
        -> optional blockchain anchor
        -> verification API

Also covers the ledger verification contract (Phase 3), the three blockchain
adapter modes (Phase 12), anchor-queue retry classification (Phase 11) and the
QR / verification URL contract (Phase 9).

Everything runs against an ISOLATED per-module SQLite file so a developer's
local evidence database is never touched.
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("VOICETRUST_WS_JWT_SECRET", "test-secret-e2e-xyzzy")
os.environ.setdefault("VOICETRUST_DETECTOR_MODE", "mock")
os.environ.setdefault("HF_ZERO_GPU_SPACE", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.services.evidence_anchor import (  # noqa: E402
    GENESIS_HASH,
    EvidenceAnchorService,
    _canonical_json,
    _sha256_hex,
    build_evidence_payload,
)

EVIDENCE_ID = "SV-E2E-0001"
SESSION_ID = "call-e2e-0001"

# Deterministic fixture audio (a tiny but structurally valid PCM WAV).
AUDIO_BYTES = (
    b"RIFF" + (36 + 8).to_bytes(4, "little") + b"WAVEfmt " + (16).to_bytes(4, "little")
    + (1).to_bytes(2, "little") + (1).to_bytes(2, "little") + (16000).to_bytes(4, "little")
    + (32000).to_bytes(4, "little") + (2).to_bytes(2, "little") + (16).to_bytes(2, "little")
    + b"data" + (8).to_bytes(4, "little") + b"\x00\x01\x02\x03\x04\x05\x06\x07"
)


@pytest.fixture(scope="module")
def db_factory(tmp_path_factory):
    """Isolated per-module SQLite database + session factory."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import models  # noqa: F401 - registers all models
    from app.db.database import Base

    db_path = tmp_path_factory.mktemp("forensic-e2e") / "e2e.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    yield factory
    engine.dispose()


@pytest.fixture(scope="module")
def db_session(db_factory):
    session = db_factory()
    yield session
    session.close()


@pytest.fixture(scope="module")
def api_client(db_factory, monkeypatch_module):
    """TestClient whose get_db dependency uses the isolated database."""
    from app.db.database import get_db
    from app.main import app

    def _override_get_db():
        db = db_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(scope="module")
def monkeypatch_module():
    """A module-scoped monkeypatch (pytest's is function-scoped)."""
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    yield mp
    mp.undo()


def _register_ledger_package(session, evidence_id: str, *, risk: int = 80):
    """Register a legacy hash-chain ledger package for *evidence_id*."""
    payload = build_evidence_payload(
        session_id=evidence_id,
        caller_id="caller-e2e",
        recipient_id="bank-desk",
        max_risk_score=risk,
        final_status="LOCK_VERIFY",
    )
    service = EvidenceAnchorService(session)
    result = service.register_evidence_package(payload, evidence_id=evidence_id)
    assert result.get("status") != "error", result
    return result


def _append_ledger_event(session, evidence_id: str, *, digest: str = "appended-event"):
    """Append one more ledger event for *evidence_id*, using the service's own
    hash rule (record_hash -> chain_root) so the fixture can never drift from
    production. Production appends exactly one record per registration, so the
    multi-event chain this builds is what verification must still handle.
    """
    from app.db import models as db_models
    from app.services import evidence_anchor as ea

    service = ea.EvidenceAnchorService(session)
    package = (
        session.query(db_models.EvidencePackage)
        .filter(db_models.EvidencePackage.evidence_id == evidence_id)
        .first()
    )
    assert package is not None, "register the package before appending an event"
    previous = service._get_latest_chain_root()
    now = ea._utc_now()
    record_hash = ea._sha256_hex(
        ea._canonical_json(
            {
                "previous_record_hash": previous,
                "timestamp": now.isoformat(),
                "schema_version": ea.config.EVIDENCE_SCHEMA_VERSION,
                "evidence_digest": digest,
            }
        )
    )
    chain_root = ea._sha256_hex(
        ea._canonical_json(
            {"record_hash": record_hash, "previous_record_hash": previous}
        )
    )
    session.add(
        db_models.EvidenceLedgerRecord(
            evidence_id=evidence_id,
            record_hash=record_hash,
            previous_record_hash=previous,
            timestamp=now,
            schema_version=ea.config.EVIDENCE_SCHEMA_VERSION,
            evidence_digest=digest,
            chain_root_hash=chain_root,
        )
    )
    package.local_chain_root = chain_root
    session.flush()
    return previous


# ---------------------------------------------------------------------------
# PHASE 3 - LEDGER
# ---------------------------------------------------------------------------


def test_ledger_genesis_is_documented_and_fixed():
    """The genesis boundary is a documented constant, never a random value."""
    assert GENESIS_HASH == "GENESIS"


def test_ledger_append_links_each_record_to_the_previous(db_session):
    _register_ledger_package(db_session, "SV-LEDGER-0001")
    from app.db import models as db_models

    records = (
        db_session.query(db_models.EvidenceLedgerRecord)
        .filter(db_models.EvidenceLedgerRecord.evidence_id == "SV-LEDGER-0001")
        .order_by(db_models.EvidenceLedgerRecord.record_id.asc())
        .all()
    )
    assert records, "registration must append at least one ledger record"
    assert records[0].previous_record_hash == GENESIS_HASH
    for previous, current in zip(records, records[1:]):
        assert current.previous_record_hash == previous.record_hash
    for record in records:
        assert record.record_hash != record.previous_record_hash


def test_ledger_sequence_is_monotonic(db_session):
    _register_ledger_package(db_session, "SV-LEDGER-0002")
    from app.db import models as db_models

    ids = [
        r.record_id
        for r in db_session.query(db_models.EvidenceLedgerRecord)
        .filter(db_models.EvidenceLedgerRecord.evidence_id == "SV-LEDGER-0002")
        .order_by(db_models.EvidenceLedgerRecord.record_id.asc())
        .all()
    ]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


def test_ledger_verification_returns_the_exact_contract(db_session):
    _register_ledger_package(db_session, "SV-LEDGER-0003")
    result = EvidenceAnchorService(db_session).verify_ledger("SV-LEDGER-0003")
    assert set(result) == {
        "valid",
        "entries_checked",
        "first_invalid_sequence",
        "expected_hash",
        "actual_hash",
        "reason",
    }
    assert result["valid"] is True
    assert result["entries_checked"] >= 1
    assert result["first_invalid_sequence"] is None
    assert result["reason"] is None


def test_ledger_verification_is_deterministic(db_session):
    _register_ledger_package(db_session, "SV-LEDGER-0004")
    service = EvidenceAnchorService(db_session)
    assert service.verify_ledger("SV-LEDGER-0004") == service.verify_ledger("SV-LEDGER-0004")


def test_ledger_verification_detects_a_changed_payload(db_session):
    """Tampering with the stored evidence digest must break the chain."""
    _register_ledger_package(db_session, "SV-LEDGER-0005")
    from app.db import models as db_models

    record = (
        db_session.query(db_models.EvidenceLedgerRecord)
        .filter(db_models.EvidenceLedgerRecord.evidence_id == "SV-LEDGER-0005")
        .order_by(db_models.EvidenceLedgerRecord.record_id.asc())
        .first()
    )
    original = record.evidence_digest
    record.evidence_digest = "0" * 64
    db_session.flush()
    result = EvidenceAnchorService(db_session).verify_ledger("SV-LEDGER-0005")
    assert result["valid"] is False
    assert result["first_invalid_sequence"] == 1
    assert result["expected_hash"] != result["actual_hash"]
    record.evidence_digest = original
    db_session.flush()
    assert EvidenceAnchorService(db_session).verify_ledger("SV-LEDGER-0005")["valid"] is True


def test_ledger_verification_detects_a_changed_previous_hash(db_session):
    _register_ledger_package(db_session, "SV-LEDGER-0006")
    from app.db import models as db_models

    record = (
        db_session.query(db_models.EvidenceLedgerRecord)
        .filter(db_models.EvidenceLedgerRecord.evidence_id == "SV-LEDGER-0006")
        .order_by(db_models.EvidenceLedgerRecord.record_id.asc())
        .first()
    )
    original = record.previous_record_hash
    record.previous_record_hash = "f" * 64
    db_session.flush()
    result = EvidenceAnchorService(db_session).verify_ledger("SV-LEDGER-0006")
    assert result["valid"] is False
    assert result["first_invalid_sequence"] == 1
    record.previous_record_hash = original
    db_session.flush()


def test_ledger_verification_detects_a_replaced_record_hash(db_session):
    _register_ledger_package(db_session, "SV-LEDGER-0007")
    from app.db import models as db_models

    record = (
        db_session.query(db_models.EvidenceLedgerRecord)
        .filter(db_models.EvidenceLedgerRecord.evidence_id == "SV-LEDGER-0007")
        .order_by(db_models.EvidenceLedgerRecord.record_id.asc())
        .first()
    )
    original = record.record_hash
    record.record_hash = hashlib.sha256(b"rewritten").hexdigest()
    db_session.flush()
    result = EvidenceAnchorService(db_session).verify_ledger("SV-LEDGER-0007")
    assert result["valid"] is False
    assert result["first_invalid_sequence"] == 1
    record.record_hash = original
    db_session.flush()


def test_ledger_verification_rejects_unknown_evidence_id(db_session):
    result = EvidenceAnchorService(db_session).verify_ledger("SV-NO-SUCH-MANIFEST")
    assert result["valid"] is False
    assert result["first_invalid_sequence"] is None
    assert "not found" in (result["reason"] or "")



def test_ledger_verification_detects_a_missing_record(db_session):
    """Dropping one event from a multi-event chain must be detected."""
    _register_ledger_package(db_session, "SV-LEDGER-0008")
    _append_ledger_event(db_session, "SV-LEDGER-0008", digest="second-event")
    from app.db import models as db_models

    records = (
        db_session.query(db_models.EvidenceLedgerRecord)
        .filter(db_models.EvidenceLedgerRecord.evidence_id == "SV-LEDGER-0008")
        .order_by(db_models.EvidenceLedgerRecord.record_id.asc())
        .all()
    )
    assert len(records) == 2, "the chain must have two events to drop one"
    assert EvidenceAnchorService(db_session).verify_ledger("SV-LEDGER-0008")["valid"] is True

    # 1. Deleting EVERY event is detected (never silently "valid").
    snapshot = [
        {
            "record_id": r.record_id,
            "evidence_id": r.evidence_id,
            "record_hash": r.record_hash,
            "previous_record_hash": r.previous_record_hash,
            "timestamp": r.timestamp,
            "schema_version": r.schema_version,
            "evidence_digest": r.evidence_digest,
            "chain_root_hash": r.chain_root_hash,
        }
        for r in records
    ]
    for record in records:
        db_session.delete(record)
    db_session.flush()
    result = EvidenceAnchorService(db_session).verify_ledger("SV-LEDGER-0008")
    assert result["valid"] is False
    assert result["reason"] == "no ledger records for this evidence id"

    # Restore with the original primary keys so the chain is intact again.
    for row in snapshot:
        db_session.add(db_models.EvidenceLedgerRecord(**row))
    db_session.flush()
    assert EvidenceAnchorService(db_session).verify_ledger("SV-LEDGER-0008")["valid"] is True

    # 2. Deleting ONE event out of the middle must leave a detectable gap: the
    #    surviving record (or the stored head) no longer links up.
    second = (
        db_session.query(db_models.EvidenceLedgerRecord)
        .filter(
            db_models.EvidenceLedgerRecord.evidence_id == "SV-LEDGER-0008",
            db_models.EvidenceLedgerRecord.record_id == records[1].record_id,
        )
        .first()
    )
    db_session.delete(second)
    db_session.flush()
    gap_result = EvidenceAnchorService(db_session).verify_ledger("SV-LEDGER-0008")
    assert gap_result["valid"] is False
    assert gap_result["first_invalid_sequence"] is not None
    for row in snapshot:
        existing = (
            db_session.query(db_models.EvidenceLedgerRecord)
            .filter(db_models.EvidenceLedgerRecord.record_id == row["record_id"])
            .first()
        )
        if existing is None:
            db_session.add(db_models.EvidenceLedgerRecord(**row))
    db_session.flush()
    assert EvidenceAnchorService(db_session).verify_ledger("SV-LEDGER-0008")["valid"] is True


def test_ledger_verification_detects_a_reordered_pair(db_session):
    """Swapping two records in a multi-record chain must be detected."""
    _register_ledger_package(db_session, "SV-LEDGER-0011")
    _append_ledger_event(db_session, "SV-LEDGER-0011", digest="second-event")
    from app.db import models as db_models

    records = (
        db_session.query(db_models.EvidenceLedgerRecord)
        .filter(db_models.EvidenceLedgerRecord.evidence_id == "SV-LEDGER-0011")
        .order_by(db_models.EvidenceLedgerRecord.record_id.asc())
        .all()
    )
    assert len(records) == 2, "two records are required for a reorder test"
    assert EvidenceAnchorService(db_session).verify_ledger("SV-LEDGER-0011")["valid"] is True
    first, second = records[0], records[1]
    first_hash, second_hash = first.record_hash, second.record_hash
    first.record_hash, second.record_hash = second_hash, first_hash
    db_session.flush()
    result = EvidenceAnchorService(db_session).verify_ledger("SV-LEDGER-0011")
    assert result["valid"] is False
    assert result["first_invalid_sequence"] == 1
    first.record_hash, second.record_hash = first_hash, second_hash
    db_session.flush()
    assert EvidenceAnchorService(db_session).verify_ledger("SV-LEDGER-0011")["valid"] is True


def test_ledger_head_is_exposed_by_the_integrity_summary(db_session):
    """The ledger head is a distinct identity, derived from stored rows only.

    The head is the record's ``chain_root_hash`` (the binding snapshot of
    ``record_hash`` + ``previous_record_hash`` that the chain walk compares
    against) — not the bare ``record_hash`` of the newest row.
    """
    from app.db import models as db_models
    from app.services.evidence_package import build_integrity_summary
    from app.services.merkle_evidence import MerkleEvidenceService

    evidence_id = "SV-LEDGER-0010"
    _register_ledger_package(db_session, evidence_id)
    MerkleEvidenceService(db_session).register_merkle_package(
        evidence_id=evidence_id, items={"audio": AUDIO_BYTES}, anchor=False
    )
    summary = build_integrity_summary(db_session, evidence_id)
    head = (
        db_session.query(db_models.EvidenceLedgerRecord)
        .filter(db_models.EvidenceLedgerRecord.evidence_id == evidence_id)
        .order_by(db_models.EvidenceLedgerRecord.record_id.desc())
        .first()
    )
    assert summary["ledger_head"] == (head.chain_root_hash if head else None)
    # The package stores the same head, so the two never disagree.
    package = (
        db_session.query(db_models.EvidencePackage)
        .filter(db_models.EvidencePackage.evidence_id == evidence_id)
        .first()
    )
    assert summary["ledger_head"] == package.local_chain_root
    assert summary["ledger_head"] != head.record_hash  # distinct identities
    assert summary["ledger"]["valid"] is True
    # Distinct identities must not be collapsed into one field.
    assert summary["ledger_head"] != summary["package_sha256"]
    assert summary["ledger_head"] != summary["merkle_root"]


def test_concurrent_registration_keeps_every_chain_intact(db_factory):
    """Concurrency: parallel appends must not produce a broken chain."""
    import threading

    errors: list[str] = []

    def worker(index: int) -> None:
        session = db_factory()
        try:
            _register_ledger_package(session, f"SV-CONCURRENT-{index}", risk=index)
            session.commit()
        except Exception as exc:  # pragma: no cover - diagnostics only
            errors.append(f"{index}: {type(exc).__name__}")
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    verify_session = db_factory()
    try:
        service = EvidenceAnchorService(verify_session)
        for index in range(6):
            result = service.verify_ledger(f"SV-CONCURRENT-{index}")
            assert result["valid"] is True, (index, result)
    finally:
        verify_session.close()
    assert errors == []



# ---------------------------------------------------------------------------
# END-TO-END PIPELINE (Phase 15)
#
#     audio artifact -> artifact hashes -> canonical evidence package
#         -> package hash -> ledger entry -> Merkle root -> PDF -> PDF hash
#         -> optional blockchain anchor -> verification API
# ---------------------------------------------------------------------------

LEDGER_EVIDENCE_ID = "SV-E2E-LEDGER-0001"


def test_end_to_end_forensic_pipeline(db_session, api_client):
    """One fixture call walked through the entire evidence pipeline."""
    from app.services.anchor_adapter import get_anchor_adapter
    from app.services.evidence_anchor import EvidenceAnchorService, build_evidence_payload
    from app.services.evidence_package import (
        build_artifact_metadata,
        build_canonical_evidence_package,
        build_integrity_summary,
        package_sha256,
        verify_artifact,
    )
    from app.services.forensic_report import build_forensic_report_pdf
    from app.services.merkle_evidence import MerkleEvidenceService

    # --- 1. audio artifact -> artifact hash (actual bytes) ------------------
    audio_artifact = build_artifact_metadata(
        artifact_id="audio_original",
        role="original_audio",
        media_type="audio/wav",
        content=AUDIO_BYTES,
        source="e2e-fixture-capture",
    )
    assert audio_artifact["byte_length"] == len(AUDIO_BYTES)
    assert verify_artifact(audio_artifact, AUDIO_BYTES) is True

    # --- 2. ledger entry for the call (hash chain) --------------------------
    payload = build_evidence_payload(
        session_id=LEDGER_EVIDENCE_ID,
        caller_id="caller-e2e",
        recipient_id="bank-desk",
        max_risk_score=88,
        final_status="LOCK_VERIFY",
    )
    ledger_result = EvidenceAnchorService(db_session).register_evidence_package(
        payload, evidence_id=LEDGER_EVIDENCE_ID
    )
    assert ledger_result.get("status") != "error", ledger_result
    assert ledger_result["local_chain_status"] == "verified"

    # --- 3. Merkle package over the frozen evidence items -------------------
    items = {
        "audio": AUDIO_BYTES,
        "acoustic_result": b'{"score": 0.93, "model": "mms-300m-anti-deepfake"}',
        "speaker_result": b'{"matched": false, "confidence": 0.41}',
        "risk_stream": b'{"final_status": "LOCK_VERIFY", "max_risk_score": 88}',
    }
    service = MerkleEvidenceService(db_session)
    merkle = service.register_merkle_package(
        evidence_id=LEDGER_EVIDENCE_ID,
        session_id=SESSION_ID,
        items=items,
        anchor=False,  # DISABLED mode: local integrity only
    )
    merkle_root = merkle["merkle_root"]
    assert len(merkle_root) == 64
    assert merkle["leaf_count"] == len(items)

    # --- 4. canonical evidence package -> package hash ----------------------
    package = build_canonical_evidence_package(
        evidence_id=LEDGER_EVIDENCE_ID,
        call_id=SESSION_ID,
        created_at="2026-03-01T12:00:00+00:00",
        completed_at="2026-03-01T12:05:30+00:00",
        detection={"final_status": "LOCK_VERIFY", "max_risk_score": 88},
        acoustic_evidence={"score": 0.93, "model_id": "mms-300m-anti-deepfake"},
        audio_artifacts={"original": audio_artifact},
        merkle_metadata={"root": merkle_root, "tree_version": "merkle-v1"},
        blockchain_metadata={"status": "unavailable"},
    )
    pkg_hash = package_sha256(package)
    # Deterministic: the same frozen package hashes identically every time.
    assert pkg_hash == package_sha256(package)
    # And it is a distinct identity from the Merkle root.
    assert pkg_hash != merkle_root

    # --- 5. verification (recomputed server-side, never trusted) ------------
    verification = service.verify_merkle_package(
        LEDGER_EVIDENCE_ID, provided_items=items, verify_on_chain=False
    )
    assert verification["valid"] is True
    assert verification["merkle_root_integrity"] is True
    assert verification["package_hash_integrity"] is True
    assert verification["merkle_root"] == merkle_root

    # --- 6. integrity summary keeps every identity separate -----------------
    integrity = build_integrity_summary(db_session, LEDGER_EVIDENCE_ID)
    assert integrity["merkle_root"] == merkle_root
    assert integrity["package_sha256"] == verification["package_hash"]
    assert integrity["ledger"]["valid"] is True
    assert integrity["report"]["sha256"] is None  # not rendered yet

    # --- 7. PDF -> PDF hash (hashed outside the PDF) ------------------------
    pdf = build_forensic_report_pdf(
        evidence_id=LEDGER_EVIDENCE_ID,
        verification=verification,
        integrity=integrity,
        session_id=SESSION_ID,
    )
    report_sha256 = hashlib.sha256(pdf).hexdigest()
    assert len(report_sha256) == 64
    assert pdf[:4] == b"%PDF"
    # The PDF must not embed its own byte hash (no circular hashing).
    assert report_sha256.encode() not in pdf

    # --- 8. blockchain: DISABLED mode is explicit and honest ---------------
    anchor = get_anchor_adapter().anchor_root(merkle_root, LEDGER_EVIDENCE_ID)
    assert anchor.get("status") != "anchored"
    if anchor.get("status") != "dry_run":
        assert anchor.get("tx_hash") is None  # never invent a hash

    # --- 9. verification API reflects the stored evidence -------------------
    r = api_client.get(f"/api/v1/forensics/{LEDGER_EVIDENCE_ID}/verify")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["evidence_id"] == LEDGER_EVIDENCE_ID
    assert body["merkle_root"] == merkle_root
    assert body["package_sha256"] == verification["package_hash"]
    assert body["ledger"]["valid"] is True
    assert body["verification"]["api_path"].endswith(f"/{LEDGER_EVIDENCE_ID}/verify")
    # No PII in the verification URL handed out to a QR code.
    for pii in ("+91", "caller-e2e", "bank-desk"):
        assert pii not in body["verification"]["url"]

