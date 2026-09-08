"""
Ephemeral, in-memory tracking of active calls: ring buffers, running risk
timelines, and TTL-based expiry. No raw audio or session state touches disk
here -- see db/models.py for what *does* get written (metadata only) at call
end, which is what keeps this architecture privacy-preserving.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.config import SESSION_TTL_SECONDS
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
    # Judge-demo hook: lets the frontend's backup audio injection toggle
    # deterministically force a scripted acoustic score (see stream.py).
    forced_acoustic_score: Optional[float] = None

    def touch(self) -> None:
        self.last_seen = time.time()

    def record_risk_point(self, point: Dict) -> None:
        self.risk_timeline.append(point)
        self.current_risk_score = point["risk_score"]

    def is_expired(self) -> bool:
        return (time.time() - self.last_seen) > SESSION_TTL_SECONDS


class SessionManager:
    """Process-local session store. Swap for Redis before scaling past one worker."""

    def __init__(self):
        self._sessions: Dict[str, CallSession] = {}

    def create_session(self, caller_id: str, recipient_id: str) -> CallSession:
        call_id = str(uuid.uuid4())
        session = CallSession(call_id=call_id, caller_id=caller_id, recipient_id=recipient_id)
        self._sessions[call_id] = session
        return session

    def get(self, call_id: str) -> Optional[CallSession]:
        session = self._sessions.get(call_id)
        if session and session.is_expired():
            self.end_session(call_id, status="COMPLETED")
            return None
        return session

    def end_session(self, call_id: str, status: str = "COMPLETED") -> Optional[CallSession]:
        session = self._sessions.pop(call_id, None)
        if session:
            session.status = status
        return session

    def purge_expired(self) -> None:
        expired = [cid for cid, s in self._sessions.items() if s.is_expired()]
        for cid in expired:
            self.end_session(cid, status="COMPLETED")


# Single shared instance for the app's lifetime -- fine for a single-process
# hackathon deployment; move this state to Redis before scaling horizontally.
session_manager = SessionManager()
