"""Session-cache snapshots must not persist transcript or explanation text."""
from __future__ import annotations

import json
import time

from app.core.session_manager import CallSession, SessionManager


class _RedisCapture:
    def __init__(self, payload: str | None = None, ttl: int = 3600) -> None:
        self.payload = payload
        self.ttl_value = ttl
        self.stored_ttl: int | None = None

    def get(self, _key: str) -> str | None:
        return self.payload

    def ttl(self, _key: str) -> int:
        return self.ttl_value

    def setex(self, _key: str, ttl: int, payload: str) -> None:
        self.payload = payload
        self.stored_ttl = ttl


def test_redis_session_snapshot_keeps_only_minimal_risk_timeline_fields() -> None:
    manager = SessionManager()
    redis_capture = _RedisCapture()
    manager._redis_client = redis_capture
    session = CallSession(call_id="call-privacy", caller_id="caller", recipient_id="bank")
    session.risk_timeline = [
        {
            "timestamp": 1.25,
            "risk_score": 72,
            "status": "LOCK_VERIFY",
            "transcript": "send the OTP now",
            "rationale": ["OTP request"],
            "intent_risks": [
                {"matched_phrase": "send the OTP", "evidence": "send the OTP now"}
            ],
            "detector": {"provider_response": "internal detail"},
        }
    ]

    manager._store_session(session.call_id, session)

    assert redis_capture.payload is not None
    stored = json.loads(redis_capture.payload)
    assert stored["risk_timeline"] == [
        {"timestamp": 1.25, "risk_score": 72, "status": "LOCK_VERIFY"}
    ]
    assert "send the OTP" not in redis_capture.payload
    assert "transcript" not in redis_capture.payload
    assert "intent_risks" not in redis_capture.payload
    assert "detector" not in redis_capture.payload


def test_loading_legacy_redis_session_scrubs_sensitive_fields_in_place() -> None:
    old_payload = json.dumps(
        {
            "call_id": "call-old-cache",
            "caller_id": "caller",
            "recipient_id": "bank",
            "last_seen": time.time(),
            "risk_timeline": [
                {
                    "timestamp": 1.25,
                    "risk_score": 72,
                    "status": "LOCK_VERIFY",
                    "transcript": "send the OTP now",
                    "rationale": ["OTP request"],
                }
            ],
        }
    )
    manager = SessionManager()
    manager._redis_available = True
    redis_capture = _RedisCapture(old_payload, ttl=2700)
    manager._redis_client = redis_capture

    loaded = manager.get("call-old-cache")

    assert loaded is not None
    assert loaded.risk_timeline == [
        {"timestamp": 1.25, "risk_score": 72, "status": "LOCK_VERIFY"}
    ]
    assert redis_capture.payload is not None
    assert "send the OTP" not in redis_capture.payload
    assert redis_capture.stored_ttl == 2700
