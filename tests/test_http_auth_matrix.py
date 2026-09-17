"""Task C: HTTP JWT auth matrix for /risk and /terminate.

WebSocket auth was already working, yet /risk and /terminate returned 401 because
the frontend never sent the call JWT. These tests pin the server contract that
the client must satisfy:

  valid owner bearer  -> 200
  missing token       -> 401  (anonymous access is never allowed)
  invalid token       -> 401
  expired token       -> 401
  other user's token  -> 403  (IDOR/BOLA, never 200)
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest

os.environ.setdefault("VOICETRUST_WS_JWT_SECRET", "test-secret-auth-matrix-abc123")
os.environ.setdefault("VOICETRUST_WS_AUTH_ENABLED", "true")
os.environ.setdefault("VOICETRUST_DETECTOR_MODE", "mock")
os.environ.setdefault("HF_ZERO_GPU_SPACE", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.core.ws_auth import create_access_token


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def call(client: TestClient):
    """Start a call and return (call_id, valid_owner_token)."""
    caller_id = "auth-matrix-caller"
    resp = client.post(
        "/api/v1/call/start",
        json={"caller_id": caller_id, "recipient_id": "bank"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # The token returned by /call/start is the credential the frontend must reuse.
    return body["call_id"], body["token"]


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_risk_rejects_missing_token_with_401(client, call) -> None:
    call_id, _ = call
    resp = client.get(f"/api/v1/call/{call_id}/risk")
    assert resp.status_code == 401
    assert "WWW-Authenticate" in resp.headers


def test_risk_rejects_invalid_token_with_401(client, call) -> None:
    call_id, _ = call
    resp = client.get(
        f"/api/v1/call/{call_id}/risk", headers=_bearer("not.a.jwt")
    )
    assert resp.status_code == 401


def test_risk_rejects_expired_token_with_401(client, call) -> None:
    call_id, caller_id = call
    expired = create_access_token(caller_id, timedelta(seconds=-30))
    resp = client.get(f"/api/v1/call/{call_id}/risk", headers=_bearer(expired))
    assert resp.status_code == 401


def test_risk_accepts_valid_owner_token_with_200(client, call) -> None:
    call_id, token = call
    resp = client.get(f"/api/v1/call/{call_id}/risk", headers=_bearer(token))
    assert resp.status_code == 200
    assert resp.json()["call_id"] == call_id


def test_risk_rejects_another_users_valid_token_with_403(client, call) -> None:
    call_id, _ = call
    other = create_access_token("someone-else", timedelta(minutes=5))
    resp = client.get(f"/api/v1/call/{call_id}/risk", headers=_bearer(other))
    assert resp.status_code == 403


def test_terminate_rejects_missing_token_with_401(client, call) -> None:
    call_id, _ = call
    resp = client.post(f"/api/v1/call/{call_id}/terminate")
    assert resp.status_code == 401


def test_terminate_rejects_invalid_token_with_401(client, call) -> None:
    call_id, _ = call
    resp = client.post(
        f"/api/v1/call/{call_id}/terminate", headers=_bearer("garbage.token.value")
    )
    assert resp.status_code == 401


def test_terminate_rejects_expired_token_with_401(client, call) -> None:
    call_id, caller_id = call
    expired = create_access_token(caller_id, timedelta(seconds=-30))
    resp = client.post(
        f"/api/v1/call/{call_id}/terminate", headers=_bearer(expired)
    )
    assert resp.status_code == 401


def test_terminate_accepts_valid_owner_token_with_200(client, call) -> None:
    call_id, token = call
    resp = client.post(f"/api/v1/call/{call_id}/terminate", headers=_bearer(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["call_id"] == call_id
    assert body["status"] == "COMPLETED"
    # Persistence outcome is reported explicitly, never implied.
    assert body["persistence"] in {"ok", "degraded"}


def test_terminate_rejects_another_users_valid_token_with_403(client, call) -> None:
    call_id, _ = call
    other = create_access_token("intruder", timedelta(minutes=5))
    resp = client.post(f"/api/v1/call/{call_id}/terminate", headers=_bearer(other))
    assert resp.status_code == 403