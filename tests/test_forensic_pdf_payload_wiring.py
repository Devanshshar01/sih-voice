"""F1 — frozen payload / artifact wiring into the forensic PDF (Phase 1 blocker).

`build_forensic_report_pdf(payload=..., artifacts=...)` used to raise
``TypeError: _assemble_report_data() got an unexpected keyword argument
'payload'`` — the production report path (``render_and_register_report`` ->
``GET /forensics/merkle/{id}/report.pdf``) was broken.

These tests pin the corrected contract:

  * payload/artifacts keyword arguments are accepted
  * page 2 (DETECTION SUMMARY) renders detection + model fields sourced from
    the FROZEN payload when the verification envelope does not carry them
  * verification data takes precedence over the payload on conflict
  * page 3 (INTEGRITY) renders the caller-computed artifact SHA-256 digests
  * identical inputs still render byte-identical PDFs (invariant=1)
  * the production HTTP path renders the payload's model_id end-to-end

Nothing is invented: only fields present in the passed payload/artifacts are
rendered; missing values keep the explicit "Not available" fallback.
"""
from __future__ import annotations

import hashlib
import io
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("VOICETRUST_WS_JWT_SECRET", "test-secret-pdf-payload-xyzzy")
os.environ.setdefault("VOICETRUST_DETECTOR_MODE", "mock")
os.environ.setdefault("HF_ZERO_GPU_SPACE", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.forensic_report import (  # noqa: E402
    build_forensic_report_pdf,
)

EVIDENCE_ID = "SV-PDF-PAYLOAD-0001"
SESSION_ID = "call-pdf-payload-0001"
PACKAGE_HASH = "a" * 64
MERKLE_ROOT = "b" * 64
LEDGER_HEAD = "c" * 64

MODEL_ID = "nii-yamagishilab/mms-300m-anti-deepfake"
ARTIFACT_SHA = "e" * 64


def _verification(**overrides):
    """Production-shaped verification: NO detection/model_metadata/artifacts.

    The real canonical verification envelope (``_canonical_result``) does not
    carry a detection block — page 2/3 content must therefore come from the
    frozen payload / caller-computed artifacts.
    """
    data = {
        "evidence_id": EVIDENCE_ID,
        "session_id": SESSION_ID,
        "valid": True,
        "package_hash_integrity": True,
        "merkle_root_integrity": True,
        "merkle_root": MERKLE_ROOT,
        "package_hash": PACKAGE_HASH,
        "created_at": "2026-03-01T12:00:00+00:00",
        "schema_version": "phase10-v1",
        "anchor_status": "unavailable",
    }
    data.update(overrides)
    return data


def _integrity():
    return {
        "evidence_id": EVIDENCE_ID,
        "schema_version": "phase10-v1",
        "package_sha256": PACKAGE_HASH,
        "merkle_root": MERKLE_ROOT,
        "ledger_head": LEDGER_HEAD,
        "ledger": {"valid": True, "entries_checked": 1},
        "blockchain": {"status": "unavailable", "confirmed": False, "simulated": False},
    }


def _payload(**overrides):
    """A frozen legacy evidence snapshot (what the client registered)."""
    data = {
        "evidence_id": EVIDENCE_ID,
        "session_id": SESSION_ID,
        "max_risk_score": 88,
        "final_status": "LOCK_VERIFY",
        "acoustic_peak": 0.93,
        "model_metadata": {
            "detector_mode": "remote",
            "model_id": MODEL_ID,
            "model_revision": "main",
        },
        "detection": {
            "risk_status": "LOCK_VERIFY",
            "model_status": "SYNTHETIC",
            "confidence": 0.91,
        },
    }
    data.update(overrides)
    return data


def _render(payload=None, artifacts=None, verification=None):
    return build_forensic_report_pdf(
        evidence_id=EVIDENCE_ID,
        verification=verification if verification is not None else _verification(),
        integrity=_integrity(),
        session_id=SESSION_ID,
        payload=payload,
        artifacts=artifacts,
    )


def _pages(pdf_bytes: bytes) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    return [page.extract_text() or "" for page in reader.pages]


# ---------------------------------------------------------------------------
# Direct contract: kwargs accepted, pages populated, precedence, reproducible
# ---------------------------------------------------------------------------


def test_payload_and_artifacts_kwargs_are_accepted():
    pdf = _render(payload=_payload(), artifacts=[{
        "artifact_id": "canonical_manifest",
        "role": "evidence_manifest",
        "media_type": "application/json",
        "byte_length": 128,
        "sha256": ARTIFACT_SHA,
    }])
    assert pdf[:5] == b"%PDF-"


def test_page2_renders_detection_and_model_fields_from_frozen_payload():
    pdf = _render(payload=_payload())
    page2 = _pages(pdf)[1]
    # Detection summary sourced from the frozen payload.
    assert "DETECTION SUMMARY" in page2
    assert "LOCK_VERIFY" in page2          # risk_status (payload final_status/detection)
    assert "SYNTHETIC" in page2            # model_status (payload detection block)
    assert "88" in page2                   # risk_score (payload max_risk_score)
    # Model provenance sourced from the frozen payload.
    assert MODEL_ID in page2
    assert "remote" in page2               # detector_mode


def test_page3_renders_artifact_sha256_from_artifacts_argument():
    artifacts = [
        {
            "artifact_id": "canonical_manifest",
            "role": "evidence_manifest",
            "media_type": "application/json",
            "byte_length": 128,
            "sha256": ARTIFACT_SHA,
        }
    ]
    pdf = _render(payload=_payload(), artifacts=artifacts)
    page3 = _pages(pdf)[2]
    assert "INTEGRITY" in page3
    assert "canonical_manifest" in page3
    assert ARTIFACT_SHA in "".join(page3.split())


def test_verification_data_takes_precedence_over_payload():
    verification = _verification(
        detection={
            "risk_status": "WARN",
            "model_status": "GENUINE",
            "risk_score": 0.42,
        },
        model_metadata={"detector_mode": "cloud", "model_id": "server-side-model"},
    )
    pdf = _render(payload=_payload(), verification=verification)
    page2 = _pages(pdf)[1]
    # Verification (recomputed server-side) wins over the frozen payload.
    assert "WARN" in page2
    assert "GENUINE" in page2
    assert "server-side-model" in page2
    assert "SYNTHETIC" not in page2
    assert MODEL_ID not in page2


def test_missing_payload_renders_explicit_fallbacks_not_none():
    pdf = _render(payload=None, artifacts=None)
    text = "\n".join(_pages(pdf))
    assert "Not available" in text
    assert "None" not in text
    assert "null" not in text


def test_identical_payload_and_artifacts_yield_identical_bytes():
    """ReportLab invariant=1 reproducibility survives the payload wiring."""
    kwargs = dict(
        payload=_payload(),
        artifacts=[{
            "artifact_id": "canonical_manifest",
            "role": "evidence_manifest",
            "media_type": "application/json",
            "byte_length": 128,
            "sha256": ARTIFACT_SHA,
        }],
    )
    first = _render(**kwargs)
    second = _render(**kwargs)
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()


# ---------------------------------------------------------------------------
# Production HTTP path: register -> report.pdf renders the payload's model id
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def api_client(tmp_path_factory):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.database import get_db
    from app.db.models import Base

    db_path = tmp_path_factory.mktemp("pdf-payload-wiring") / "evidence.db"
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False)

    from fastapi.testclient import TestClient

    from app.main import app

    def _override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_db, None)


def test_report_pdf_endpoint_renders_payload_model_id(api_client):
    """GET /forensics/merkle/{id}/report.pdf: 200, 5 pages, payload model id.

    This is the exact production path that previously raised TypeError from
    the ``payload=`` keyword argument.
    """
    from pypdf import PdfReader

    from app.core.ws_auth import create_access_token

    headers = {
        "Authorization": f"Bearer {create_access_token('pdf-payload-api-caller')}"
    }
    evidence_id = "SV-PDF-PAYLOAD-API-1"
    payload = _payload(evidence_id=evidence_id)
    payload["session_id"] = evidence_id
    reg = api_client.post(
        "/api/v1/forensics/register", json={"payload": payload}, headers=headers
    )
    assert reg.status_code == 200, reg.text

    pdf = api_client.get(
        f"/api/v1/forensics/merkle/{evidence_id}/report.pdf", headers=headers
    )
    assert pdf.status_code == 200, pdf.text
    assert pdf.content[:5] == b"%PDF-"

    reader = PdfReader(io.BytesIO(pdf.content))
    assert len(reader.pages) == 5

    page2 = reader.pages[1].extract_text() or ""
    assert MODEL_ID in page2

    # report_sha256 round-trip: stored header == verify envelope, never inside PDF.
    header = pdf.headers.get("X-Report-SHA256")
    assert header is not None and len(header) == 64
    assert hashlib.sha256(pdf.content).hexdigest() == header
    verify = api_client.get(f"/api/v1/forensics/{evidence_id}/verify")
    assert verify.status_code == 200
    assert verify.json()["report"]["sha256"] == header
    # No circular hashing: the final byte hash never appears in rendered text.
    rendered_text = "".join(
        "".join((page.extract_text() or "").split()) for page in reader.pages
    )
    assert header not in rendered_text
