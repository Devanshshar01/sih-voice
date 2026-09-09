"""
Active-call tracking with a restart-safe backend option.

This module now prefers a Redis-backed session store when configured while
preserving the in-memory local-dev path as a fallback. The goal is to ensure
active calls survive a backend restart instead of vanishing silently.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.config import REDIS_URL, SESSION_STORE_BACKEND, SESSION_TTL_SECONDS
from app.services.audio_processor import RingBuffer


@dataclass
class CallSession:
    call_id: str
    caller_id: str
    recipient_id: str
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    ring_buffer: RingBuffer = field(default_factory=RingBuffer)
    risk_timeline: List[Dict] = field(default_factory=list)
    current_risk_score: int = 0
    status: str = "ACTIVE"
    verified: bool = False
    forced_acoustic_score: Optional[float] = None

    def touch(self) -> None:
        self.last_seen = time.time()

    def record_risk_point(self, point: Dict) -> None:
        self.risk_timeline.append(point)
        self.current_risk_score = point["risk_score"]

    def is_expired(self) -> bool:
        return (time.time() - self.last_seen) > SESSION_TTL_SECONDS


class SessionManager:
    """Session store that can use in-memory local dev or Redis-backed persistence."""

    def __init__(self):
        self._sessions: Dict[str, CallSession] = {}
        self._redis_available = SESSION_STORE_BACKEND == "redis"
        self._redis_client = None
        if self._redis_available:
            try:
                import redis

                self._redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
                self._redis_client.ping()
            except Exception:
                self._redis_available = False

    def create_session(self, caller_id: str, recipient_id: str) -> CallSession:
        call_id = str(uuid.uuid4())
        session = CallSession(call_id=call_id, caller_id=caller_id, recipient_id=recipient_id)
        self._sessions[call_id] = session
        if self._redis_available:
            self._store_session(call_id, session)
        return session

    def get(self, call_id: str) -> Optional[CallSession]:
        if self._redis_available:
            session = self._load_session(call_id)
            if session is None:
                return None
            if session.is_expired():
                self.end_session(call_id, status="COMPLETED")
                return None
            return session

        session = self._sessions.get(call_id)
        if session and session.is_expired():
            self.end_session(call_id, status="COMPLETED")
            return None
        return session

    def end_session(self, call_id: str, status: str = "COMPLETED") -> Optional[CallSession]:
        session = self._load_session(call_id) if self._redis_available else self._sessions.pop(call_id, None)
        if session:
            session.status = status
            if self._redis_available:
                self._delete_session(call_id)
        return session

    def sync_session(self, session: CallSession) -> None:
        if self._redis_available:
            self._store_session(session.call_id, session)
        else:
            self._sessions[session.call_id] = session

    def purge_expired(self) -> None:
        if self._redis_available:
            return

        expired = [cid for cid, s in self._sessions.items() if s.is_expired()]
        for cid in expired:
            self.end_session(cid, status="COMPLETED")

    def _store_session(self, call_id: str, session: CallSession) -> None:
        if self._redis_client is None:
            return
        payload = {
            "call_id": session.call_id,
            "caller_id": session.caller_id,
            "recipient_id": session.recipient_id,
            "created_at": session.created_at,
            "last_seen": session.last_seen,
            "current_risk_score": session.current_risk_score,
            "status": session.status,
            "verified": session.verified,
            "forced_acoustic_score": session.forced_acoustic_score,
            "risk_timeline": session.risk_timeline,
        }
        self._redis_client.setex(f"call:{call_id}", SESSION_TTL_SECONDS, json.dumps(payload))

    def _load_session(self, call_id: str) -> Optional[CallSession]:
        if self._redis_client is None:
            return self._sessions.get(call_id)
        payload = self._redis_client.get(f"call:{call_id}")
        if not payload:
            return None
        data = json.loads(payload)
        session = CallSession(
            call_id=data["call_id"],
            caller_id=data["caller_id"],
            recipient_id=data["recipient_id"],
            created_at=data.get("created_at", time.time()),
            last_seen=data.get("last_seen", time.time()),
            current_risk_score=data.get("current_risk_score", 0),
            status=data.get("status", "ACTIVE"),
            verified=data.get("verified", False),
            forced_acoustic_score=data.get("forced_acoustic_score"),
        )
        session.risk_timeline = data.get("risk_timeline", [])
        return session

    def _delete_session(self, call_id: str) -> None:
        if self._redis_client is not None:
            self._redis_client.delete(f"call:{call_id}")


session_manager = SessionManager()
