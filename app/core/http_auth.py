"""HTTP bearer authentication dependency for session-scoped endpoints.

SECURITY (B2/B10):
  HTTP endpoints that access or mutate call-session resources must verify that
  the authenticated principal owns the requested resource (IDOR/BOLA prevention).

  The same JWT system used for WebSocket authentication is reused here.
  Bearer token format: Authorization: Bearer <jwt>

  Ownership verification:
    - The JWT ``sub`` claim must match ``session.caller_id`` (for call endpoints)
    - Unknown resources return 404 (not 403) to prevent resource enumeration.

  Development bypass:
    - If VOICETRUST_WS_AUTH_ENABLED=false in a non-production environment,
      auth checks are skipped (same policy as WebSocket auth).
    - IS_PRODUCTION=true always enforces auth regardless of the flag.

  F6C coverage:
    - ``require_call_owner``   — path-parameter call endpoints (risk, action,
      terminate, verification challenges with body call_id via
      ``verify_call_owner``).
    - ``require_authenticated`` — endpoints with no single-owner context
      (anchor queue/flush, speaker vault, evidence registration): any valid
      principal, never anonymous.
    - ``assert_evidence_owner`` — evidence reads when the owning session is
      still resolvable (403 for non-owners; expired sessions fall back to
      authenticated access over opaque evidence ids).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import Header, HTTPException, status

from app.core.ws_auth import _effective_auth_enabled, _validate_token
from app.core.session_manager import session_manager

logger = logging.getLogger("satyavoice.http_auth")


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    """Extract the raw JWT from 'Bearer <token>' header value."""
    if not authorization:
        return None
    parts = authorization.strip().split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return None


def _authenticate_bearer(authorization: Optional[str]) -> str:
    """Validate a Bearer token and return its subject (no ownership check).

    Raises 401 when the token is missing/invalid. Fails closed when the
    signing secret is unavailable (production without a configured secret).
    """
    raw_token = _extract_bearer(authorization)
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide a Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    subject = _validate_token(raw_token)
    if subject is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return subject


def require_authenticated(
    authorization: Optional[str] = Header(default=None),
) -> Optional[str]:
    """FastAPI dependency: any valid principal (no ownership context).

    Used for endpoints that must never be anonymous but are not scoped to a
    single call/session (anchor queue/flush, speaker vault, evidence
    registration). Returns the subject, or None when auth is disabled by the
    development bypass (never possible in production).
    """
    if not _effective_auth_enabled():
        return None  # development bypass (IS_PRODUCTION always enforces)
    return _authenticate_bearer(authorization)


def verify_call_owner(call_id: str, authorization: Optional[str]) -> str:
    """Core ownership check (IDOR/BOLA prevention) for a call_id.

    Non-dependency variant so handlers whose call_id arrives in the request
    BODY (e.g. /call/action, /verification/*) can enforce the same policy as
    the path-parameter dependency :func:`require_call_owner`.

    - Returns the authenticated subject (caller_id) on success.
    - Raises 401 if no/invalid token (when auth is enabled).
    - Raises 404 if the session is not found (prevents enumeration).
    - Raises 403 if the session exists but the caller doesn't own it.
    """
    if not _effective_auth_enabled():
        # Auth disabled (development): still verify the session exists.
        session = session_manager.get(call_id)
        if not session:
            raise HTTPException(status_code=404, detail="Call session not found or expired.")
        return session.caller_id

    subject = _authenticate_bearer(authorization)

    # Session must exist (404 rather than 403 to prevent call_id enumeration)
    session = session_manager.get(call_id)
    if not session:
        raise HTTPException(status_code=404, detail="Call session not found or expired.")

    # Ownership check (IDOR/BOLA prevention)
    if session.caller_id != subject:
        logger.warning(
            "IDOR attempt on call_id=%s by subject (redacted); access denied.",
            call_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: you do not own this session.",
        )

    return subject


def assert_evidence_owner(subject: Optional[str], session_id: Optional[str]) -> None:
    """Enforce evidence ownership when the owning session is resolvable.

    Evidence rows outlive call sessions, so ownership can only be checked
    while the session is still known: if ``session_id`` maps to a live session
    owned by someone else than ``subject``, this raises 403. When the session
    has expired (historical evidence) or auth is disabled, any authenticated
    principal may read it — evidence ids are opaque, unguessable tokens and
    the verification payload contains commitments only (no PII).
    """
    if subject is None or not session_id:
        return
    session = session_manager.get(session_id)
    if session is None:
        return
    if session.caller_id != subject:
        logger.warning(
            "IDOR attempt on evidence session_id=%s by subject (redacted); access denied.",
            session_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: you do not own this evidence.",
        )


def require_call_owner(
    call_id: str,
    authorization: Optional[str] = Header(default=None),
) -> str:
    """FastAPI dependency: verify the requester owns the given call_id.

    - Returns the authenticated subject (caller_id) on success.
    - Raises HTTP 401 if no/invalid token (when auth is enabled).
    - Raises HTTP 404 if the session is not found (prevents enumeration).
    - Raises HTTP 403 if the session exists but the caller doesn't own it.

    Usage:
        @router.get("/{call_id}/risk")
        def get_risk(call_id: str, _subject: str = Depends(require_call_owner)):
            ...
    """
    return verify_call_owner(call_id, authorization)
