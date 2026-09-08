"""
Step-up (out-of-band) verification for high-risk calls.

The prototype simulates a TOTP challenge in-process. Swap `_validate_code`
for a real provider (e.g. Twilio Verify, an authenticator-app TOTP secret)
before this goes anywhere near production.
"""
import random
import time
from typing import Dict, Tuple

from fastapi import APIRouter, HTTPException

from app import config
from app.config import RiskStatus
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
    return code


def _validate_code(call_id: str, code: str) -> bool:
    challenge = _active_challenges.get(call_id)
    if challenge is None:
        return False
    expected, expires_at = challenge
    if time.time() >= expires_at:
        _active_challenges.pop(call_id, None)
        return False
    return expected == code


@router.post("/request", response_model=VerificationRequestResponse)
def request_challenge(payload: VerificationRequest):
    session = session_manager.get(payload.call_id)
    if not session:
        raise HTTPException(status_code=404, detail="Call session not found or expired.")
    if session.current_risk_score < 70:
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
def submit_challenge(payload: VerificationChallengeRequest):
    session = session_manager.get(payload.call_id)
    if not session:
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
