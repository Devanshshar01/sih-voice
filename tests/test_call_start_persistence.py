"""Task B: /call/start persistence semantics.

The production defect was an ambiguous state: the session INSERT failed but the
endpoint still returned HTTP 200, so clients believed a monitored call existed
while every per-window RiskEvent write failed on its foreign key.

Chosen contract (no ambiguity):
  - persistence is REQUIRED by default -> failure returns 503, and no in-memory
    session is left behind to look usable
  - VOICETRUST_DB_PERSISTENCE=best_effort opts in explicitly -> 200 with an
    explicit INITIATED_DEGRADED status and persistence short-circuited
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("VOICETRUST_WS_JWT_SECRET", "test-secret-call-start-abc123")
os.environ.setdefault("VOICETRUST_WS_AUTH_ENABLED", "true")
os.environ.setdefault("VOICETRUST_DETECTOR_MODE", "mock")
os.environ.setdefault("HF_ZERO_GPU_SPACE", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app import config
from app.api.v1 import call as call_api
from app.core.session_manager import session_manager


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


def _start(client: TestClient, caller_id: str):
    return client.post(
        "/api/v1/call/start",
        json={"caller_id": caller_id, "recipient_id": "bank-helpdesk"},
    )


def test_start_call_persists_and_returns_a_usable_session(client: TestClient) -> None:
    resp = _start(client, "persist-ok")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "INITIATED"
    assert body["token"]
    # Session is retrievable (the authenticated /risk and /terminate path).
    assert session_manager.get(body["call_id"]) is not None


def test_persistence_failure_returns_503_when_required(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(config, "PERSISTENCE_REQUIRED", True)
    monkeypatch.setattr(call_api, "commit_with_retry", lambda *a, **k: False)

    resp = _start(client, "persist-required-fail")

    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["error_code"] == "SESSION_PERSISTENCE_UNAVAILABLE"
    assert detail["status"] == "error"
    # A failed persist must not leave a session that looks callable.
    assert not any(
        s.caller_id == "persist-required-fail" for s in session_manager._sessions.values()
    )


def test_persistence_required_is_the_default(client: TestClient) -> None:
    # No VOICETRUST_DB_PERSISTENCE is set in this environment.
    assert config.DB_PERSISTENCE_MODE == "required"
    assert config.PERSISTENCE_REQUIRED is True


def test_explicit_best_effort_mode_marks_the_call_degraded(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(config, "PERSISTENCE_REQUIRED", False)
    monkeypatch.setattr(call_api, "commit_with_retry", lambda *a, **k: False)

    resp = _start(client, "persist-best-effort")

    assert resp.status_code == 200
    body = resp.json()
    # Degradation is explicit, never a plain "INITIATED" success.
    assert body["status"] == "INITIATED_DEGRADED"
    session = session_manager.get(body["call_id"])
    assert session is not None
    assert session.persistence_degraded is True
