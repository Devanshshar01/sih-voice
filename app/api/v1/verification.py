"""
Step-up (out-of-band) verification for high-risk calls.

SECURITY (B12 + F6B/F6C):
  _active_challenges is pruned of expired entries on every read/write to
  prevent unbounded memory growth from callers that never submit a code.
  - The generated challenge code is NEVER returned in the HTTP response
    (F6B). It is delivered out of band: production must plug a real channel
    (SMS / authenticator push) into ``_deliver_challenge``; the development
    demo reads it from the server log.
  - Both /request and /challenge enforce call ownership (F6C): the bearer
    subject must own the call_id, so an attacker can neither dispatch a
    challenge for someone else's call nor brute-force the 6-digit code.

The prototype simulates a TOTP challenge in-process. Swap ``_validate_code``
and ``_deliver_challenge`` for a real provider (e.g. Twilio Verify, an
authenticator-app TOTP secret) before this goes anywhere near production.
"""
import logging
import random
import time
from typing import Dict, Optional, Tuple

from fastapi import APIRouter, Header, HTTPException

from app import config
from app.config import RiskStatus
from app.core.http_auth import verify_call_owner
from app.core.session_manager import session_manager
from app.models.schemas import VerificationChallengeRequest, VerificationChallengeResponse
from app.models.schemas import (
    VerificationChallengeRequest,
    VerificationChallengeResponse,
    VerificationRequest,
    VerificationRequestResponse,
)

logger = logging.getLogger("satyavoice.verification")

router = APIRouter(prefix="/verification", tags=["verification"])

# call_id -> expected code, generated when a session first crosses HIGH risk.
_active_challenges: Dict[str, Tuple[str, float]] = {}


def _prune_expired_challenges() -> None:
    """Remove expired challenge entries (B12: prevent unbounded dict growth)."""
    now = time.time()
    expired = [k for k, (_, exp) in _active_challenges.items() if now >= exp]
    for k in expired:
        _active_challenges.pop(k, None)


def issue_challenge(call_id: str) -> str:
    """Generate and store a challenge code for a call.

    Returns the code to the CALLER OF THIS FUNCTION ONLY (server-side). It
    must never be placed in an HTTP response — see ``_deliver_challenge``.
    """
    _prune_expired_challenges()  # keep dict bounded (B12)
    code = f"{random.randint(0, 999999):06d}"
    _active_challenges[call_id] = (
        code,
        time.time() + config.TOTP_CHALLENGE_TIMEOUT_SECONDS,
    )
    return code


def _deliver_challenge(call_id: str, code: str) -> None:
    """Simulated OUT-OF-BAND delivery of the challenge code (F6B).

    The code is never included in an HTTP response. Development/demo: the
    operator reads the code from the server log (clearly marked). Production:
    no code is logged either — plug a real out-of-band channel (SMS,
    authenticator push) in here before enabling production MFA.
    """
    if config.IS_PRODUCTION:
        logger.warning(
            "MFA challenge issued for call_id=%s; no out-of-band delivery "
            "channel is configured, so no code was delivered.",
            call_id,
        )
        return
    logger.info(
        "DEMO MFA delivery (server log only, never over HTTP): "
        "call_id=%s code=%s",
        call_id,
        code,
    )


def _validate_code(call_id: str, code: str) -> bool:
    _prune_expired_challenges()  # keep dict bounded (B12)
    challenge = _active_challenges.get(call_id)
    if challenge is None:
        return False
    expected, expires_at = challenge
    if time.time() >= expires_at:
        _active_challenges.pop(call_id, None)
        return False
    return expected == code


@router.post("/request", response_model=VerificationRequestResponse)
def request_challenge(
    payload: VerificationRequest,
    authorization: Optional[str] = Header(default=None),
):
    # F6C: only the authenticated owner of the call may dispatch a challenge.
    verify_call_owner(payload.call_id, authorization)
    session = session_manager.get(payload.call_id)
    if not session:
        raise HTTPException(status_code=404, detail="Call session not found or expired.")
    if session.current_risk_score <= config.RISK.LOCK_VERIFY_THRESHOLD:
        raise HTTPException(
            status_code=409,
            detail="Verification is only required after the call reaches a high-risk state.",
        )

    code = issue_challenge(payload.call_id)
    _deliver_challenge(payload.call_id, code)
    # F6B: the response carries metadata only — never the code itself.
    return VerificationRequestResponse(
        expires_in_seconds=config.TOTP_CHALLENGE_TIMEOUT_SECONDS,
        delivery_channel=(
            "Server log (development demo)"
            if not config.IS_PRODUCTION
            else "Registered security device"
        ),
    )


@router.post("/challenge", response_model=VerificationChallengeResponse)
def submit_challenge(
    payload: VerificationChallengeRequest,
    authorization: Optional[str] = Header(default=None),
):
    # F6C: ownership is required here too — without it, anyone who can reach
    # the endpoint could brute-force the 6-digit code for any call.
    verify_call_owner(payload.call_id, authorization)
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
