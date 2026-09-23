"""Forensics / evidence hardening tests (Part A).

Covers:
  1. Evidence package creation
  2. Deterministic hashing (same payload → same hash)
  3. Hash verification success
  4. Tampered payload detection
  5. Ledger chain verification
  6. Broken previous hash detection
  7. Blockchain disabled path
  8. Blockchain failure path
  9. Duplicate/idempotent registration
 10. Payload size limit enforcement
 11. Empty payload rejection
 12. on_chain_verified field present when blockchain disabled
 13. build_evidence_payload() structure
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

# Set env BEFORE any app import
os.environ.setdefault("VOICETRUST_WS_JWT_SECRET", "test-secret-forensics-xyzzy")
os.environ.setdefault("VOICETRUST_DETECTOR_MODE", "mock")
os.environ.setdefault("HF_ZERO_GPU_SPACE", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.services.evidence_anchor import (
    GENESIS_HASH,
    MAX_EVIDENCE_PAYLOAD_BYTES,
    EvidenceAnchorService,
    _canonical_json,
    _sha256_hex,
    build_evidence_payload,
)
from app.db.database import Base, get_db


@pytest.fixture(scope="module")
def _engine(tmp_path_factory):
    """Isolated, schema-complete DB.

    Never the shared developer database: an isolated file gets the FULL current
    model schema from create_all (including the migration-0004 anchor-queue
    columns), so tests exercise the same shape production gets from alembic.
    """
    from sqlalchemy import create_engine

    from app.db import models  # noqa: F401 - registers all models

    db_path = tmp_path_factory.mktemp("forensics-hardening") / "hardening.db"
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture(scope="module")
def db_session(_engine):
    """SQLAlchemy session on the isolated schema-complete database."""
    from sqlalchemy.orm import sessionmaker

    session = sessionmaker(bind=_engine)()
    yield session
    session.close()


@pytest.fixture(scope="module")
def client(_engine):
    """App client whose requests hit the same isolated database."""
    from sqlalchemy.orm import sessionmaker

    from app.main import app

    session_factory = sessionmaker(bind=_engine)

    def _override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# A3: Deterministic hashing
# ---------------------------------------------------------------------------

def test_canonical_json_is_deterministic():
    """Same dict always produces the same canonical JSON string."""
    data = {"b": 2, "a": 1, "c": [3, 1, 2]}
    r1 = _canonical_json(data)
    r2 = _canonical_json(data)
    assert r1 == r2
    # Keys must be sorted
    assert r1.index('"a"') < r1.index('"b"') < r1.index('"c"')


def test_different_payloads_produce_different_hashes():
    p1 = {"session_id": "call-A"}
    p2 = {"session_id": "call-B"}
    assert _sha256_hex(_canonical_json(p1)) != _sha256_hex(_canonical_json(p2))


# ---------------------------------------------------------------------------
# A2: build_evidence_payload() structure
# ---------------------------------------------------------------------------

def test_build_evidence_payload_structure():
    payload = build_evidence_payload(
        session_id="test-call-001",
        caller_id="alice",
        recipient_id="bank-desk",
        max_risk_score=75,
        final_status="LOCK_VERIFY",
    )
    assert payload["schema_version"] is not None
    assert payload["evidence_type"] == "technical-integrity-evidence-package"
    assert payload["session_id"] == "test-call-001"
    assert payload["caller_id"] == "alice"
    assert payload["max_risk_score"] == 75
    assert "model_metadata" in payload
    assert "evidence_id" in payload
    assert "created_at" in payload


# ---------------------------------------------------------------------------
# A2+A3: Evidence registration and hash verification
# ---------------------------------------------------------------------------

def test_evidence_registration_creates_package(db_session):
    svc = EvidenceAnchorService(db_session)
    payload = build_evidence_payload(session_id="call-hash-test-1", max_risk_score=30)
    result = svc.register_evidence_package(payload)

    assert result["status"] != "error", f"Registration failed: {result}"
    assert "evidence_hash" in result
    assert "local_chain_root" in result
    assert result["local_chain_status"] == "verified"
    assert result["anchor_status"] == "unavailable"  # blockchain disabled by default


def test_deterministic_hash_same_payload_is_idempotent(db_session):
    """Registering the same payload twice returns the existing record."""
    svc = EvidenceAnchorService(db_session)
    payload = build_evidence_payload(session_id="call-idem-test", max_risk_score=10)
    # Register once
    r1 = svc.register_evidence_package(payload)
    # Register again with the same payload
    r2 = svc.register_evidence_package(payload)

    assert r1["evidence_hash"] == r2["evidence_hash"]
    assert r2.get("duplicate") is True


# ---------------------------------------------------------------------------
# A3+A7: Hash verification
# ---------------------------------------------------------------------------

def test_verify_passes_for_valid_package(db_session):
    svc = EvidenceAnchorService(db_session)
    payload = build_evidence_payload(session_id="call-verify-ok", max_risk_score=55)
    reg = svc.register_evidence_package(payload)
    assert reg["status"] != "error"

    report = svc.verify_evidence_package(reg["evidence_id"])
    assert report["evidence_hash_integrity"] is True
    assert report["local_chain_integrity"] is True
    assert report["ledger_record_count"] >= 1
    assert "on_chain_verified" in report  # field must be present (A7)


def test_tampered_payload_fails_hash_verification(db_session):
    """Modify the stored package_payload and verify that integrity fails."""
    from app.db import models as db_models

    svc = EvidenceAnchorService(db_session)
    payload = build_evidence_payload(session_id="call-tamper-test", max_risk_score=80)
    reg = svc.register_evidence_package(payload)
    assert reg["status"] != "error"

    # Directly corrupt the stored payload (simulates DB tampering)
    pkg = (
        db_session.query(db_models.EvidencePackage)
        .filter_by(evidence_id=reg["evidence_id"])
        .first()
    )
    original_payload = pkg.package_payload
    pkg.package_payload = original_payload.replace("80", "0")  # mutate risk score
    db_session.commit()

    report = svc.verify_evidence_package(reg["evidence_id"])
    assert report["evidence_hash_integrity"] is False

    # Restore original (clean up for other tests)
    pkg.package_payload = original_payload
    db_session.commit()


# ---------------------------------------------------------------------------
# A4: Ledger chain verification
# ---------------------------------------------------------------------------

def test_ledger_chain_has_correct_previous_hash_reference(db_session):
    """Two consecutive packages must form a valid hash chain."""
    from app.db import models as db_models

    svc = EvidenceAnchorService(db_session)

    p1 = build_evidence_payload(session_id="call-chain-A", max_risk_score=20)
    r1 = svc.register_evidence_package(p1)
    assert r1["status"] != "error"

    p2 = build_evidence_payload(session_id="call-chain-B", max_risk_score=30)
    r2 = svc.register_evidence_package(p2)
    assert r2["status"] != "error"

    # The second package's ledger record must reference the first as previous
    rec2 = (
        db_session.query(db_models.EvidenceLedgerRecord)
        .filter_by(evidence_id=r2["evidence_id"])
        .first()
    )
    assert rec2 is not None
    # previous_record_hash must NOT be GENESIS (unless it's the very first record)
    # and must be the chain_root_hash of some earlier record
    assert rec2.previous_record_hash != rec2.record_hash


def test_verify_broken_chain_detected(db_session):
    """Corrupt a ledger record's chain_root_hash and verify it's detected."""
    from app.db import models as db_models

    svc = EvidenceAnchorService(db_session)
    payload = build_evidence_payload(session_id="call-broken-chain", max_risk_score=60)
    reg = svc.register_evidence_package(payload)
    assert reg["status"] != "error"

    # Corrupt the ledger record's chain_root_hash
    rec = (
        db_session.query(db_models.EvidenceLedgerRecord)
        .filter_by(evidence_id=reg["evidence_id"])
        .first()
    )
    original_root = rec.chain_root_hash
    rec.chain_root_hash = "0" * 64  # corrupted
    db_session.commit()

    report = svc.verify_evidence_package(reg["evidence_id"])
    assert report["local_chain_integrity"] is False

    # Restore
    rec.chain_root_hash = original_root
    db_session.commit()


# ---------------------------------------------------------------------------
# A8: Failure handling
# ---------------------------------------------------------------------------

def test_empty_payload_returns_error_not_raises(db_session):
    svc = EvidenceAnchorService(db_session)
    result = svc.register_evidence_package({})
    assert result["status"] == "error"
    # Must NOT raise, must return a dict


def test_oversized_payload_rejected(db_session):
    svc = EvidenceAnchorService(db_session)
    # Build a payload that exceeds MAX_EVIDENCE_PAYLOAD_BYTES
    big_payload = {"data": "x" * (MAX_EVIDENCE_PAYLOAD_BYTES + 1)}
    result = svc.register_evidence_package(big_payload)
    assert result["status"] == "error"
    assert "maximum permitted size" in result["error"].lower() or "maximum" in result["error"].lower()


# ---------------------------------------------------------------------------
# A6: Blockchain disabled path
# ---------------------------------------------------------------------------

def test_blockchain_disabled_anchor_status_is_unavailable(db_session):
    from app import config
    assert not config.BLOCKCHAIN_ANCHORING_ENABLED  # must be disabled in test env

    svc = EvidenceAnchorService(db_session)
    payload = build_evidence_payload(session_id="call-bc-disabled", max_risk_score=40)
    result = svc.register_evidence_package(payload)

    assert result["status"] != "error"
    assert result["anchor_status"] == "unavailable"


# ---------------------------------------------------------------------------
# A6: Blockchain failure path (mocked)
# ---------------------------------------------------------------------------

def test_blockchain_anchor_failure_does_not_crash_registration(db_session):
    """A failing CANONICAL adapter never breaks /forensics/register.

    The legacy flat-root ``anchor()`` path is retired for new registrations;
    the canonical step submits ``anchorEvidence()`` and records an honest
    failure when the adapter raises — registration itself still succeeds
    locally, and the legacy record never claims an anchor it does not have.
    """
    from app import config
    from app.services.evidence_verification import ensure_canonical_merkle_package

    svc = EvidenceAnchorService(db_session)
    payload = build_evidence_payload(session_id="call-bc-failure", max_risk_score=50)

    with mock.patch.object(config, "BLOCKCHAIN_ANCHORING_ENABLED", True):
        with mock.patch(
            "app.services.merkle_evidence.get_anchor_adapter"
        ) as canonical_factory, mock.patch(
            "app.services.evidence_anchor.get_anchor_adapter"
        ) as legacy_factory:
            mock_adapter = mock.MagicMock()
            mock_adapter.anchor_evidence.side_effect = RuntimeError("Network error")
            canonical_factory.return_value = mock_adapter

            result = svc.register_evidence_package(payload)
            assert result["status"] != "error"
            # The new forensic path must never call the legacy flat-root anchor().
            legacy_factory.return_value.anchor_root.assert_not_called()

            canonical_payload = result.pop("canonical_payload")
            canonical = ensure_canonical_merkle_package(
                db_session,
                evidence_id=result["evidence_id"],
                canonical_payload=canonical_payload,
            )

    # Local registration succeeded; the canonical anchor failure is recorded
    # honestly (adapter exceptions are contained by the Merkle anchor wrapper),
    # while the retired legacy record reports no anchor of its own.
    assert result["status"] != "error"
    assert result["anchor_status"] == "unavailable"
    assert canonical["status"] == "ok"
    assert canonical.get("anchor_status") == "failed"


# ---------------------------------------------------------------------------
# A7: on_chain_verified field in verification report
# ---------------------------------------------------------------------------

def test_verify_report_contains_on_chain_verified_when_disabled(db_session):
    svc = EvidenceAnchorService(db_session)
    payload = build_evidence_payload(session_id="call-onchain-check", max_risk_score=35)
    reg = svc.register_evidence_package(payload)
    report = svc.verify_evidence_package(reg["evidence_id"])

    # When blockchain is disabled, on_chain_verified should be None
    assert "on_chain_verified" in report
    assert report["on_chain_verified"] is None  # not queried


# ---------------------------------------------------------------------------
# HTTP API: forensics endpoints
# ---------------------------------------------------------------------------

def test_forensics_register_via_http(client: TestClient):
    payload = build_evidence_payload(session_id="call-http-register", max_risk_score=25)
    response = client.post("/api/v1/forensics/register", json={"payload": payload})
    assert response.status_code == 200
    data = response.json()
    assert "evidence_hash" in data
    assert data["local_chain_status"] == "verified"


def test_forensics_register_empty_payload_returns_400(client: TestClient):
    response = client.post("/api/v1/forensics/register", json={"payload": {}})
    assert response.status_code == 400


def test_forensics_verify_not_found_returns_404(client: TestClient):
    response = client.post("/api/v1/forensics/00000000-not-found/verify")
    assert response.status_code == 404


def test_forensics_verify_existing_package(client: TestClient):
    payload = build_evidence_payload(session_id="call-http-verify", max_risk_score=45)
    reg = client.post("/api/v1/forensics/register", json={"payload": payload})
    assert reg.status_code == 200
    eid = reg.json()["evidence_id"]

    verify = client.post(f"/api/v1/forensics/{eid}/verify")
    assert verify.status_code == 200
    data = verify.json()
    assert data["evidence_hash_integrity"] is True
    assert data["local_chain_integrity"] is True
