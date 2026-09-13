"""
Tests for WebSocket authentication and authorization (ws_auth.py + stream.py).

Test cases per specification:
  1. Valid token + own call   -> accepted (connection established, streaming works).
  2. No token                 -> rejected (close 4001).
  3. Invalid/garbage token    -> rejected (close 4001).
  4. Expired token            -> rejected (close 4001).
  5. Valid token, wrong owner -> rejected (close 4003, IDOR/BOLA prevention).
  6. Malformed bearer data    -> rejected (close 4001).
  7. Development auth bypass  -> disabled in production (IS_PRODUCTION guard).
  8. Existing authorized WS   -> still works end-to-end after auth added.

All tests run with VOICETRUST_DETECTOR_MODE=mock (via env setup) so the
inference pipeline never makes real network calls.
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path
from unittest import mock

# Ensure env vars are set BEFORE any app imports
os.environ.setdefault("VOICETRUST_WS_JWT_SECRET", "test-secret-do-not-use-in-prod-xyzzy")
os.environ.setdefault("VOICETRUST_DETECTOR_MODE", "mock")
os.environ.setdefault("HF_ZERO_GPU_SPACE", "dummy_space_for_tests")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.ws_auth import (
    WS_CLOSE_FORBIDDEN,
    WS_CLOSE_POLICY_VIOLATION,
    create_access_token,
)

_TEST_SECRET = os.environ["VOICETRUST_WS_JWT_SECRET"]
_ALGORITHM = "HS256"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def _start_call(client: TestClient, caller_id: str, recipient_id: str = "recipient-01") -> str:
    """Create a call session and return the call_id."""
    r = client.post(
        "/api/v1/call/start",
        json={"caller_id": caller_id, "recipient_id": recipient_id},
    )
    assert r.status_code == 200, r.text
    return r.json()["call_id"]


def _valid_token(subject: str, expiry: timedelta = timedelta(hours=1)) -> str:
    return create_access_token(subject=subject, expires_delta=expiry)


def _expired_token(subject: str) -> str:
    return create_access_token(subject=subject, expires_delta=timedelta(seconds=-1))


def _garbage_token() -> str:
    return "not.a.jwt.at.all"


def _wrong_secret_token(subject: str) -> str:
    import time
    payload = {"sub": subject, "iat": int(time.time()), "exp": int(time.time()) + 3600}
    return jwt.encode(payload, "totally-wrong-secret", algorithm=_ALGORITHM)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestWebSocketAuthentication:
    """All security tests for the /call/{call_id}/stream WebSocket endpoint."""

    # ------------------------------------------------------------------
    # Case 1: Valid authenticated user + own call -> accepted
    # ------------------------------------------------------------------
    def test_valid_token_own_call_accepted(self, client: TestClient) -> None:
        """A user with a valid JWT for their own call_id must be accepted."""
        caller_id = "user-valid-own-call"
        call_id = _start_call(client, caller_id)
        token = _valid_token(caller_id)

        with client.websocket_connect(f"/api/v1/call/{call_id}/stream?token={token}") as ws:
            # Connection accepted: we can send and receive data
            silence = b"\x00" * (8000 * 4)  # 8000 float32 samples of silence
            ws.send_bytes(silence)
            # The WebSocket stays open without raising WebSocketDisconnect.

    # ------------------------------------------------------------------
    # Case 2: No token -> rejected
    # ------------------------------------------------------------------
    def test_no_token_rejected(self, client: TestClient) -> None:
        """Connection without any token must be rejected."""
        caller_id = "user-no-token"
        call_id = _start_call(client, caller_id)

        with pytest.raises(Exception):
            # TestClient raises when the server closes the WebSocket before accept()
            with client.websocket_connect(f"/api/v1/call/{call_id}/stream") as ws:
                ws.receive_text()

    # ------------------------------------------------------------------
    # Case 3: Invalid token (garbage string) -> rejected
    # ------------------------------------------------------------------
    def test_invalid_token_rejected(self, client: TestClient) -> None:
        """An invalid (garbage) token must be rejected."""
        caller_id = "user-invalid-token"
        call_id = _start_call(client, caller_id)
        token = _garbage_token()

        with pytest.raises(Exception):
            with client.websocket_connect(
                f"/api/v1/call/{call_id}/stream?token={token}"
            ) as ws:
                ws.receive_text()

    # ------------------------------------------------------------------
    # Case 4: Expired token -> rejected
    # ------------------------------------------------------------------
    def test_expired_token_rejected(self, client: TestClient) -> None:
        """An expired token must be rejected even if the signature is valid."""
        caller_id = "user-expired-token"
        call_id = _start_call(client, caller_id)
        token = _expired_token(caller_id)

        with pytest.raises(Exception):
            with client.websocket_connect(
                f"/api/v1/call/{call_id}/stream?token={token}"
            ) as ws:
                ws.receive_text()

    # ------------------------------------------------------------------
    # Case 5: Valid token + another user's call -> rejected (IDOR/BOLA)
    # ------------------------------------------------------------------
    def test_valid_token_wrong_owner_rejected(self, client: TestClient) -> None:
        """A valid token must NOT grant access to another user's call_id."""
        owner_id = "user-idor-owner"
        attacker_id = "user-idor-attacker"

        # Attacker creates their own call
        _start_call(client, attacker_id)

        # Owner creates a separate call
        victim_call_id = _start_call(client, owner_id)

        # Attacker's valid token, but uses the OWNER's call_id
        attacker_token = _valid_token(attacker_id)

        with pytest.raises(Exception):
            with client.websocket_connect(
                f"/api/v1/call/{victim_call_id}/stream?token={attacker_token}"
            ) as ws:
                ws.receive_text()

    # ------------------------------------------------------------------
    # Case 6: Malformed authentication data -> rejected
    # ------------------------------------------------------------------
    def test_wrong_secret_token_rejected(self, client: TestClient) -> None:
        """A JWT signed with the wrong secret must be rejected."""
        caller_id = "user-wrong-secret"
        call_id = _start_call(client, caller_id)
        token = _wrong_secret_token(caller_id)

        with pytest.raises(Exception):
            with client.websocket_connect(
                f"/api/v1/call/{call_id}/stream?token={token}"
            ) as ws:
                ws.receive_text()

    def test_empty_token_string_rejected(self, client: TestClient) -> None:
        """An empty token query param must be rejected (treated as missing)."""
        caller_id = "user-empty-token"
        call_id = _start_call(client, caller_id)

        with pytest.raises(Exception):
            with client.websocket_connect(
                f"/api/v1/call/{call_id}/stream?token="
            ) as ws:
                ws.receive_text()

    # ------------------------------------------------------------------
    # Case 7: Development bypass is disabled in production
    # ------------------------------------------------------------------
    def test_production_always_enforces_auth(self) -> None:
        """IS_PRODUCTION=True must override VOICETRUST_WS_AUTH_ENABLED=false."""
        import app.core.ws_auth as ws_auth_module
        import app.config as config_module

        original_is_prod = config_module.IS_PRODUCTION
        original_auth_enabled = ws_auth_module._WS_AUTH_ENABLED

        try:
            config_module.IS_PRODUCTION = True
            ws_auth_module._WS_AUTH_ENABLED = False  # attempt to disable in "production"

            # Even with _WS_AUTH_ENABLED=False, production must enforce auth.
            result = ws_auth_module._effective_auth_enabled()
            assert result is True, (
                "Auth must always be enforced in production regardless of "
                "VOICETRUST_WS_AUTH_ENABLED"
            )
        finally:
            config_module.IS_PRODUCTION = original_is_prod
            ws_auth_module._WS_AUTH_ENABLED = original_auth_enabled

    def test_dev_bypass_only_works_in_non_production(self) -> None:
        """VOICETRUST_WS_AUTH_ENABLED=false must only take effect in development."""
        import app.core.ws_auth as ws_auth_module
        import app.config as config_module

        original_is_prod = config_module.IS_PRODUCTION
        original_auth_enabled = ws_auth_module._WS_AUTH_ENABLED

        try:
            config_module.IS_PRODUCTION = False
            ws_auth_module._WS_AUTH_ENABLED = False

            result = ws_auth_module._effective_auth_enabled()
            assert result is False, "Auth bypass should work in non-production"
        finally:
            config_module.IS_PRODUCTION = original_is_prod
            ws_auth_module._WS_AUTH_ENABLED = original_auth_enabled

    # ------------------------------------------------------------------
    # Case 8: Existing authorized WebSocket functionality continues to work
    # ------------------------------------------------------------------
    def test_existing_authorized_ws_still_works(self, client: TestClient) -> None:
        """After auth is added, authorized streaming must still function end-to-end."""
        caller_id = "user-e2e-test"
        call_id = _start_call(client, caller_id)
        token = _valid_token(caller_id)

        with client.websocket_connect(f"/api/v1/call/{call_id}/stream?token={token}") as ws:
            # Send a manual transcript (no real audio inference needed in mock mode)
            ws.send_text('{"transcript": "Hello this is a legitimate call."}')
            # Push enough silence to trigger a window (8 hops of 8000 samples each)
            silence = b"\x00" * (8000 * 4)  # 8000 float32 samples
            for _ in range(8):
                ws.send_bytes(silence)
            # Receive the risk telemetry
            result = ws.receive_json()
            assert "risk_score" in result
            assert "status" in result
            assert result["status"] in {"ALLOW", "WARN", "LOCK_VERIFY"}

    # ------------------------------------------------------------------
    # Non-existent call_id
    # ------------------------------------------------------------------
    def test_valid_token_nonexistent_call_rejected(self, client: TestClient) -> None:
        """A valid token for a call_id that does not exist must be rejected."""
        token = _valid_token("some-user")
        fake_call_id = "00000000-0000-0000-0000-000000000000"

        with pytest.raises(Exception):
            with client.websocket_connect(
                f"/api/v1/call/{fake_call_id}/stream?token={token}"
            ) as ws:
                ws.receive_text()
