"""
Step-up (out-of-band) verification for high-risk calls.

The prototype simulates a TOTP challenge in-process. Swap `_validate_code`
for a real provider (e.g. Twilio Verify, an authenticator-app TOTP secret)
before this goes anywhere near production.

Security (Phase-10 audit fixes):
  * Tenant binding: verification is authorized against the tenant that owns
    the call — one tenant can never request or answer another tenant's
    challenge (BOLA), including 404 indistinguishability.
  * Brute-force resistance: a per-call bounded attempt counter invalidates
    the challenge after MAX_CHALLENGE_ATTEMPTS wrong codes, so a 6-digit
    code cannot be guessed within the challenge timeout window.
"""
import random
import time
from typing import Dict, Tuple

from fastapi import APIRouter, Depends, HTTPException

from app import config
from app.config import RiskStatus
from app.core.auth import AuthContext, require_auth
from app.core.session_manager import session_manager
from app.models.schemas import VerificationChallengeRequest, VerificationChallengeResponse
from app.models.schemas import (
    VerificationChallengeRequest,
    VerificationChallengeResponse,
    VerificationRequest,
    VerificationRequestResponse,
)

router = APIRouter(prefix="/verification", tags=["verification"])

# call_id -> expected code, generated when a session first crosses HIGH risk.
_active_challenges: Dict[str, Tuple[str, float]] = {}
# call_id -> wrong-code attempts consumed by the current challenge.
_challenge_attempts: Dict[str, int] = {}

MAX_CHALLENGE_ATTEMPTS = 5


def issue_challenge(call_id: str) -> str:
    """Generate and store a challenge code for a call.

    In production this is pushed via SMS/authenticator push and never
    returned to the caller directly; the prototype returns it here purely
    so the demo UI can display it for judges.
    """
    code = f"{random.randint(0, 999999):06d}"
    _active_challenges[call_id] = (
        code,
        time.time() + config.TOTP_CHALLENGE_TIMEOUT_SECONDS,
    )
    _challenge_attempts.pop(call_id, None)
    return code


def _validate_code(call_id: str, code: str) -> bool:
    """Validate a code with bounded attempts.

    A wrong code consumes an attempt; after MAX_CHALLENGE_ATTEMPTS the
    challenge is invalidated (a fresh one must be requested). This bounds
    online guessing against the 6-digit code inside the 60 s window.
    """
    challenge = _active_challenges.get(call_id)
    if challenge is None:
        return False
    expected, expires_at = challenge
    if time.time() >= expires_at:
        _active_challenges.pop(call_id, None)
        _challenge_attempts.pop(call_id, None)
        return False
    if expected == code:
        _active_challenges.pop(call_id, None)
        _challenge_attempts.pop(call_id, None)
        return True
    attempts = _challenge_attempts.get(call_id, 0) + 1
    if attempts >= MAX_CHALLENGE_ATTEMPTS:
        _active_challenges.pop(call_id, None)
        _challenge_attempts.pop(call_id, None)
    else:
        _challenge_attempts[call_id] = attempts
    return False


def _authorized_session(call_id: str, auth: AuthContext):
    """Load the call session and enforce the tenant boundary (BOLA)."""
    session = session_manager.get(call_id)
    if not session or session.tenant_id != auth.tenant_id:
        # Wrong tenant: indistinguishable from a missing session.
        raise HTTPException(status_code=404, detail="Call session not found or expired.")
    return session


@router.post("/request", response_model=VerificationRequestResponse)
def request_challenge(payload: VerificationRequest, auth: AuthContext = Depends(require_auth)):
    session = _authorized_session(payload.call_id, auth)
    if session.status != "ACTIVE":
        raise HTTPException(status_code=404, detail="Call session not found or expired.")
    if session.current_risk_score <= config.RISK.LOCK_VERIFY_THRESHOLD:
        raise HTTPException(
            status_code=409,
            detail="Verification is only required after the call reaches a high-risk state.",
        )

    code = issue_challenge(payload.call_id)
    return VerificationRequestResponse(
        code=code,
        expires_in_seconds=config.TOTP_CHALLENGE_TIMEOUT_SECONDS,
        delivery_channel="Registered security device (demo)",
    )


@router.post("/challenge", response_model=VerificationChallengeResponse)
def submit_challenge(payload: VerificationChallengeRequest, auth: AuthContext = Depends(require_auth)):
    session = _authorized_session(payload.call_id, auth)
    if session.status != "ACTIVE":
        # A terminated call must never be unlocked, even if a challenge was
        # already in flight when it ended (race: HIGH_RISK → terminate →
        # challenge response arrives). In Redis-backed mode an ended session
        # remains readable within its TTL, so the status guard is required.
        raise HTTPException(status_code=404, detail="Call session not found or expired.")

    if _validate_code(payload.call_id, payload.code):
        session.verified = True
        session.forced_acoustic_score = None
        _active_challenges.pop(payload.call_id, None)
        return VerificationChallengeResponse(
            success=True,
            new_risk_state=RiskStatus.ALLOW,
            message="Verification succeeded. Controls unlocked.",
        )

    return VerificationChallengeResponse(
        success=False,
        new_risk_state=RiskStatus.LOCK_VERIFY,
        message="Invalid or expired code. Controls remain locked.",
    )
