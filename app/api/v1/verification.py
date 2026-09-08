"""
Step-up (out-of-band) verification for high-risk calls.

The prototype simulates a TOTP challenge in-process. Swap `_validate_code`
for a real provider (e.g. Twilio Verify, an authenticator-app TOTP secret)
before this goes anywhere near production.
"""
import random
from typing import Dict

from fastapi import APIRouter, HTTPException

from app.config import RiskStatus
from app.core.session_manager import session_manager
from app.models.schemas import VerificationChallengeRequest, VerificationChallengeResponse

router = APIRouter(prefix="/verification", tags=["verification"])

# call_id -> expected code, generated when a session first crosses HIGH risk.
_active_challenges: Dict[str, str] = {}


def issue_challenge(call_id: str) -> str:
    """Generate and store a challenge code for a call.

    In production this is pushed via SMS/authenticator push and never
    returned to the caller directly; the prototype returns it here purely
    so the demo UI can display it for judges.
    """
    code = f"{random.randint(0, 999999):06d}"
    _active_challenges[call_id] = code
    return code


def _validate_code(call_id: str, code: str) -> bool:
    expected = _active_challenges.get(call_id)
    return expected is not None and expected == code


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
