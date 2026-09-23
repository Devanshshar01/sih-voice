"""Forensic registration + verification architecture regression tests.

Covers the confirmed production incident and its fixes:

  FIX 1  identity-based registration idempotency
         (new id -> 200, same id+same snapshot -> 200 duplicate,
          same id+different snapshot -> 409 EVIDENCE_ID_CONFLICT, no mutation)
  FIX 2  race-safe defensive insert (concurrent duplicate resolves to the
         existing record instead of HTTP 500; unrelated IntegrityErrors still
         surface as real server errors)
  FIX 3  export-invariant evidence identity (repeated exports of the same
         finalized call register the same evidence_hash)
  FIX 4  /forensics/register also creates the canonical Merkle commitment
         (exactly once per evidence id)
  FIX 5  ONE canonical verification result for GET and POST /verify
  FIX 6  the QR verification URL reaches the working GET endpoint

NO migration was required: every fix is code-level (idempotency order,
canonical registration, single verification implementation). No stored evidence
is migrated, rewritten or deleted; legacy evidence stays readable (test 13).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

os.environ.setdefault("VOICETRUST_WS_JWT_SECRET", "test-secret-forensic-reg-xyzzy")
os.environ.setdefault("VOICETRUST_DETECTOR_MODE", "mock")
os.environ.setdefault("HF_ZERO_GPU_SPACE", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.db import models as db_models  # noqa: E402
from app.db.database import Base, get_db  # noqa: E402
from app.services.evidence_anchor import (  # noqa: E402
    EVIDENCE_ID_CONFLICT,
    EvidenceAnchorService,
    strip_export_scoped_fields,
)
from app.services.evidence_verification import verify_canonical_evidence  # noqa: E402

FINALIZED_WINDOW_TS = 1772360000.0  # stable, evidence-derived call boundary


def _payload(
    evidence_id: str,
    *,
    exported_at: str = "2026-03-01T12:10:00+00:00",
    risk: int = 88,
    signature: str = "deadbeef",
) -> dict:
    """A realistic client report payload (export-scoped fields included)."""
    return {
        "schema_version": "phase7-v1",
        "evidence_type": "technical-integrity-evidence-package",
        "evidence_id": evidence_id,
        "session_id": evidence_id,
        "caller_id": "caller-reg",
        "recipient_id": "bank-desk",
        "duration_seconds": 42,
        "max_risk_score": risk,
        "final_status": "LOCK_VERIFY",
        "risk_events": [{"t": 1.5, "status": "WARN"}],
        "analysis_windows": [
            {
                "window_index": 0,
                "timestamp": FINALIZED_WINDOW_TS,
                "risk_score": risk,
                "acoustic_score": 0.93,
                "status": "LOCK_VERIFY",
                "derived_data_hash": "a" * 64,
            }
        ],
        "model_metadata": {
            "detector_mode": "remote",
            "model_id": "nii-yamagishilab/mms-300m-anti-deepfake",
        },
        # Export-scoped (must never enter the evidence identity):
        "exported_at": exported_at,
        "exportedAt": exported_at,
        "package_signature": {
            "algorithm": "HMAC-SHA256 placeholder",
            "signed_by": "caller-reg",
            "signature": signature,
        },
    }


# ---------------------------------------------------------------------------
# Isolated DB + app client (never touches the developer's local evidence store)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def session_factory(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("forensic-registration") / "evidence.db"
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False)


@pytest.fixture()
def db(session_factory):
    session = session_factory()
    yield session
    session.close()


@pytest.fixture(scope="module")
def client(session_factory):
    from app.main import app

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


def _register(client: TestClient, payload: dict):
    return client.post("/api/v1/forensics/register", json={"payload": payload})


def _merkle_rows(session_factory, evidence_id: str) -> tuple[list, list]:
    """(packages, leaves) currently stored for an evidence id."""
    session = session_factory()
    try:
        packages = (
            session.query(db_models.EvidenceMerklePackage)
            .filter(db_models.EvidenceMerklePackage.evidence_id == evidence_id)
            .all()
        )
        leaves = (
            session.query(db_models.EvidenceMerkleLeaf)
            .filter(db_models.EvidenceMerkleLeaf.evidence_id == evidence_id)
            .all()
        )
        return packages, leaves
    finally:
        session.close()


# ---------------------------------------------------------------------------
# TEST 1-3: identity-based registration idempotency (FIX 1)
# ---------------------------------------------------------------------------


def test_1_first_registration_succeeds(client: TestClient):
    r = _register(client, _payload("SV-REG-0001"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["evidence_hash"]
    assert body["status"] != "error"
    # Canonical commitment created in the same call (FIX 4).
    assert body["canonical"]["merkle_root"]
    assert body["canonical"]["package_hash"]
    assert body["canonical"]["leaf_count"] == 1
    # The internal snapshot is consumed server-side, never echoed back.
    assert "canonical_payload" not in body


def test_2_same_id_same_snapshot_is_idempotent(client: TestClient):
    payload = _payload("SV-REG-0002")
    first = _register(client, payload)
    assert first.status_code == 200, first.text

    second = _register(client, payload)
    assert second.status_code == 200, second.text
    assert second.json()["duplicate"] is True
    assert second.json()["evidence_hash"] == first.json()["evidence_hash"]
    # The canonical package is reused, not re-created.
    assert second.json()["canonical"]["duplicate"] is True


def test_3_same_id_different_snapshot_is_409_conflict(client: TestClient, session_factory):
    evidence_id = "SV-REG-0003"
    first = _register(client, _payload(evidence_id, risk=88))
    assert first.status_code == 200, first.text
    existing_hash = first.json()["evidence_hash"]

    # Different finalized evidence for an already-registered id.
    conflict = _register(client, _payload(evidence_id, risk=41))
    assert conflict.status_code == 409, conflict.text
    detail = conflict.json()["detail"]
    assert detail["error_code"] == EVIDENCE_ID_CONFLICT
    assert detail["conflict"] is True
    assert detail["evidence_id"] == evidence_id
    assert detail["existing_evidence_hash"] == existing_hash
    assert detail["submitted_evidence_hash"] != existing_hash

    # No mutation in EITHER store: the first snapshot's identities are intact.
    session = session_factory()
    try:
        legacy = (
            session.query(db_models.EvidencePackage)
            .filter(db_models.EvidencePackage.evidence_id == evidence_id)
            .one()
        )
        assert legacy.evidence_hash == existing_hash
        assert '"max_risk_score":88' in legacy.package_payload
        merkle = (
            session.query(db_models.EvidenceMerklePackage)
            .filter(db_models.EvidenceMerklePackage.evidence_id == evidence_id)
            .one()
        )
        assert merkle.package_hash == first.json()["canonical"]["package_hash"]
        assert merkle.merkle_root == first.json()["canonical"]["merkle_root"]
    finally:
        session.close()

    # The verification path still reports the ORIGINAL canonical identity.
    after = client.get(f"/api/v1/forensics/{evidence_id}/verify")
    assert after.status_code == 200, after.text
    assert after.json()["package_sha256"] == first.json()["canonical"]["package_hash"]


# ---------------------------------------------------------------------------
# TEST 4-5: race-safe insert (FIX 2)
# ---------------------------------------------------------------------------


def test_4_race_duplicate_insert_returns_existing_record(db: Session):
    """A duplicate PK inserted concurrently resolves to the existing record."""
    payload = _payload("SV-REG-0004")
    service = EvidenceAnchorService(db)
    first = service.register_evidence_package(payload)
    assert first["status"] != "error"

    real_by_id = EvidenceAnchorService._package_by_evidence_id
    real_by_hash = EvidenceAnchorService._package_by_evidence_hash
    misses = {"id": 0, "hash": 0}

    def stale_by_id(self, evidence_id):
        """Miss once: the concurrent writer was not visible at check time."""
        misses["id"] += 1
        return None if misses["id"] == 1 else real_by_id(self, evidence_id)

    def stale_by_hash(self, evidence_hash):
        misses["hash"] += 1
        return None if misses["hash"] == 1 else real_by_hash(self, evidence_hash)

    # Both pre-checks are stale -> the INSERT runs -> duplicate PK -> the race
    # handler must resolve it to the existing record instead of raising.
    with mock.patch.object(
        EvidenceAnchorService, "_package_by_evidence_id", stale_by_id
    ), mock.patch.object(
        EvidenceAnchorService, "_package_by_evidence_hash", stale_by_hash
    ):
        result = service.register_evidence_package(payload)

    assert misses["id"] == 2, "the race handler must re-query by evidence_id"
    assert result["status"] != "error"
    assert result["duplicate"] is True
    assert result["evidence_hash"] == first["evidence_hash"]


def test_5_unrelated_integrity_error_is_a_real_error(db: Session):
    """A non-identity IntegrityError must NOT be masked as duplicate/conflict."""
    payload = _payload("SV-REG-0005")
    service = EvidenceAnchorService(db)

    with mock.patch.object(
        Session,
        "flush",
        side_effect=IntegrityError(
            "INSERT INTO evidence_ledger_records", {}, Exception("fk")
        ),
    ):
        result = service.register_evidence_package(payload)

    assert result["status"] == "error"
    assert result.get("duplicate") is not True
    assert result.get("error_code") != EVIDENCE_ID_CONFLICT


def test_5b_endpoint_maps_service_errors_to_500(client: TestClient):
    with mock.patch.object(
        EvidenceAnchorService,
        "register_evidence_package",
        return_value={"status": "error", "error": "database exploded"},
    ):
        r = client.post("/api/v1/forensics/register", json={"payload": {"a": 1}})
    assert r.status_code == 500



# ---------------------------------------------------------------------------
# TEST 6: repeated export of the same finalized call -> same hash (FIX 3)
# ---------------------------------------------------------------------------


def test_6_repeated_export_of_finalized_call_hashes_identically(client: TestClient):
    evidence_id = "SV-REG-0006"
    # Only the export clock (and the export-derived signature) differ.
    first = _register(
        client, _payload(evidence_id, exported_at="2026-03-01T12:10:00+00:00")
    )
    assert first.status_code == 200, first.text
    second = _register(
        client,
        _payload(
            evidence_id,
            exported_at="2026-03-01T18:55:12+00:00",
            signature="cafebabe",
        ),
    )
    assert second.status_code == 200, second.text
    assert second.json()["evidence_hash"] == first.json()["evidence_hash"]
    assert second.json()["duplicate"] is True


def test_6b_export_scoped_fields_are_removed_before_hashing(client: TestClient):
    r = _register(client, _payload("SV-REG-0007"))
    assert r.status_code == 200, r.text
    ignored = r.json()["ignored_export_fields"]
    assert "exported_at" in ignored
    assert "exportedAt" in ignored
    assert "package_signature" in ignored


def test_6c_strip_helper_keeps_genuine_evidence_fields():
    payload = _payload("SV-REG-0008")
    stripped, removed = strip_export_scoped_fields(payload)
    assert "exported_at" not in stripped
    assert "package_signature" not in stripped
    # Genuinely forensic fields survive untouched.
    assert stripped["analysis_windows"] == payload["analysis_windows"]
    assert stripped["risk_events"] == payload["risk_events"]
    assert stripped["model_metadata"] == payload["model_metadata"]
    assert stripped["duration_seconds"] == payload["duration_seconds"]
    assert removed




# ---------------------------------------------------------------------------
# TEST 7-8: canonical Merkle registration (FIX 4)
# ---------------------------------------------------------------------------


def test_7_register_creates_canonical_merkle_evidence(client: TestClient, session_factory):
    evidence_id = "SV-REG-0009"
    r = _register(client, _payload(evidence_id))
    assert r.status_code == 200, r.text
    canonical = r.json()["canonical"]
    assert canonical["merkle_root"]

    packages, leaves = _merkle_rows(session_factory, evidence_id)
    assert len(packages) == 1
    assert packages[0].merkle_root == canonical["merkle_root"]
    assert packages[0].package_hash == canonical["package_hash"]
    assert len(leaves) == canonical["leaf_count"] == 1
    # Canonical commitment rides the same frozen snapshot bytes.
    assert leaves[0].item_name == "evidence_package"


def test_8_repeated_register_does_not_duplicate_merkle_package(
    client: TestClient, session_factory
):
    evidence_id = "SV-REG-0010"
    payload = _payload(evidence_id)
    roots = set()
    for _ in range(3):
        r = _register(client, payload)
        assert r.status_code == 200, r.text
        roots.add(r.json()["canonical"]["merkle_root"])

    packages, leaves = _merkle_rows(session_factory, evidence_id)
    assert len(packages) == 1, "repeated exports must not create duplicate packages"
    assert len(leaves) == 1
    # The Merkle root is stable across repeated registrations.
    assert roots == {packages[0].merkle_root}



# ---------------------------------------------------------------------------
# TEST 9-11: canonical verification path + QR (FIX 5, FIX 6)
# ---------------------------------------------------------------------------


def test_9_get_verify_works_after_register(client: TestClient):
    evidence_id = "SV-REG-0011"
    assert _register(client, _payload(evidence_id)).status_code == 200

    r = client.get(f"/api/v1/forensics/{evidence_id}/verify")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["canonical"] is True
    assert body["storage"] == "canonical"
    assert body["valid"] is True
    assert body["package_sha256"]
    assert body["merkle_root"]
    assert body["ledger"]["valid"] is True
    assert body["integrity"]["package_hash_integrity"] is True
    assert body["integrity"]["merkle_root_integrity"] is True


def test_10_get_and_post_verify_agree(client: TestClient):
    evidence_id = "SV-REG-0012"
    assert _register(client, _payload(evidence_id)).status_code == 200

    get_body = client.get(f"/api/v1/forensics/{evidence_id}/verify").json()
    post_body = client.post(f"/api/v1/forensics/{evidence_id}/verify").json()

    for key in (
        "evidence_id",
        "canonical",
        "storage",
        "valid",
        "package_sha256",
        "merkle_root",
        "ledger_head",
        "ledger",
        "blockchain",
        "integrity",
        "evidence_hash",
        "local_chain_root",
        "local_chain_integrity",
        "ledger_record_count",
        "anchor_status",
    ):
        assert get_body[key] == post_body[key], f"GET and POST disagree on {key!r}"


def test_11_qr_verification_url_reaches_the_get_endpoint(client: TestClient):
    from app.services.forensic_report import (
        build_verification_url,
        verification_api_path,
    )

    evidence_id = "SV-REG-0013"
    assert _register(client, _payload(evidence_id)).status_code == 200

    api_path = verification_api_path(evidence_id)
    assert api_path == f"/api/v1/forensics/{evidence_id}/verify"
    # The QR target carries ONLY the opaque evidence id (no PII / no raw evidence).
    url = build_verification_url(evidence_id)
    assert url.endswith(f"?evidence={evidence_id}")
    for pii in ("+91", "caller-reg", "bank-desk"):
        assert pii not in url

    # Opening that target reaches the working GET verification endpoint.
    assert client.get(api_path).status_code == 200


def test_11b_unknown_evidence_is_404_on_both_verbs(client: TestClient):
    assert client.get("/api/v1/forensics/SV-REG-MISSING/verify").status_code == 404
    assert client.post("/api/v1/forensics/SV-REG-MISSING/verify").status_code == 404



# ---------------------------------------------------------------------------
# TEST 12-14: tamper detection, legacy readability, output hygiene
# ---------------------------------------------------------------------------


def test_12_modified_evidence_is_detected_as_invalid(client: TestClient, session_factory):
    evidence_id = "SV-REG-0014"
    assert _register(client, _payload(evidence_id)).status_code == 200
    assert client.get(f"/api/v1/forensics/{evidence_id}/verify").json()["valid"] is True

    # Tamper with the stored canonical manifest (simulates DB tampering).
    session = session_factory()
    try:
        row = (
            session.query(db_models.EvidenceMerklePackage)
            .filter(db_models.EvidenceMerklePackage.evidence_id == evidence_id)
            .first()
        )
        original = row.canonical_package
        row.canonical_package = original.replace('"evidence_package"', '"tampered"')
        session.commit()
    finally:
        session.close()

    tampered = client.get(f"/api/v1/forensics/{evidence_id}/verify").json()
    assert tampered["valid"] is False
    assert tampered["integrity"]["package_hash_integrity"] is False

    # Restore so the fixture DB stays consistent for later tests.
    session = session_factory()
    try:
        row = (
            session.query(db_models.EvidenceMerklePackage)
            .filter(db_models.EvidenceMerklePackage.evidence_id == evidence_id)
            .first()
        )
        row.canonical_package = original
        session.commit()
    finally:
        session.close()

    assert client.get(f"/api/v1/forensics/{evidence_id}/verify").json()["valid"] is True


def test_13_legacy_only_evidence_stays_readable(client: TestClient, session_factory):
    """Pre-canonical evidence is never migrated or deleted — only labelled."""
    evidence_id = "SV-REG-0015"
    assert _register(client, _payload(evidence_id)).status_code == 200

    # Simulate pre-existing legacy-only evidence: drop the canonical rows.
    session = session_factory()
    try:
        package = (
            session.query(db_models.EvidenceMerklePackage)
            .filter(db_models.EvidenceMerklePackage.evidence_id == evidence_id)
            .first()
        )
        session.delete(package)
        session.commit()
    finally:
        session.close()

    r = client.get(f"/api/v1/forensics/{evidence_id}/verify")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["canonical"] is False
    assert body["storage"] == "legacy"
    assert body["valid"] is True
    assert body["evidence_hash"]                     # legacy hash chain intact
    assert body["evidence_hash_integrity"] is True
    assert body["local_chain_integrity"] is True
    # No Merkle commitment exists -> it must be reported as absent, never faked.
    assert body["merkle_root"] is None


def test_14_integrity_output_has_no_serialization_artifacts(client: TestClient):
    evidence_id = "SV-REG-0016"
    assert _register(client, _payload(evidence_id)).status_code == 200
    raw = client.get(f"/api/v1/forensics/{evidence_id}/verify").text

    for token in ("NaN", "Infinity", "undefined", "object at 0x"):
        assert token not in raw, f"forbidden token {token!r} in integrity output"

    body = json.loads(raw)

    def _walk(value):
        if isinstance(value, float):
            assert value == value  # never NaN
            assert value not in (float("inf"), float("-inf"))
        elif isinstance(value, dict):
            for item in value.values():
                _walk(item)
        elif isinstance(value, list):
            for item in value:
                _walk(item)

    _walk(body)


def test_14b_service_level_verification_envelope(db: Session):
    """The shared verifier returns the canonical envelope directly."""
    payload = _payload("SV-REG-0017")
    registered = EvidenceAnchorService(db).register_evidence_package(payload)
    assert registered["status"] != "error"
    # Registered through the service (not the API), so no canonical package yet.
    result = verify_canonical_evidence(db, "SV-REG-0017", verify_on_chain=False)
    assert result["storage"] == "legacy"
    assert result["valid"] is True

# ---------------------------------------------------------------------------
# §5 / §9 — backend PDF report hash roundtrip + GET verification contract
# ---------------------------------------------------------------------------


def test_backend_pdf_report_hash_roundtrip(client):
    """register -> backend PDF -> report_sha256 persisted == X-Report-SHA256.

    Also proves the PDF never contains its own final hash (Phase 7, no circular
    hashing), the GET verify envelope carries the §9 contract keys, and tx/block
    metadata is exposed only for a CONFIRMED anchor.
    """
    import io as _io

    from pypdf import PdfReader

    evidence_id = "SV-REPORT-RT-1"
    response = _register(client, _payload(evidence_id))
    assert response.status_code == 200, response.text

    # --- authoritative backend PDF (the endpoint the frontend now downloads) --
    pdf = client.get(f"/api/v1/forensics/merkle/{evidence_id}/report.pdf")
    assert pdf.status_code == 200, pdf.text
    assert pdf.content[:5] == b"%PDF-"
    reader = PdfReader(_io.BytesIO(pdf.content))
    assert len(reader.pages) == 5  # required forensic report structure
    header = pdf.headers.get("X-Report-SHA256")
    assert header is not None and len(header) == 64

    # --- GET verification exposes the stored report hash ---------------------
    verify = client.get(f"/api/v1/forensics/{evidence_id}/verify")
    assert verify.status_code == 200
    body = verify.json()
    for key in (
        "evidence_id",
        "package_sha256",
        "merkle_root",
        "ledger_head",
        "report",
        "blockchain",
    ):
        assert key in body, key
    assert body["evidence_id"] == evidence_id
    assert body["report"]["sha256"] == header  # stored == returned header

    # --- PDF must NOT contain its own final SHA-256 --------------------------
    text = "".join((page.extract_text() or "") for page in reader.pages)
    assert header not in "".join(text.split())

    # --- no fabricated chain metadata ---------------------------------------
    if not body["blockchain"]["confirmed"]:
        assert body["blockchain"]["tx_hash"] is None
        assert body["blockchain"]["block_number"] is None

    # --- QR target: verification URL carries the opaque evidence id only -----
    if "verification_url" in body:
        assert evidence_id in body["verification_url"]

