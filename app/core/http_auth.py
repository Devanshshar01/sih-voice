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

  Note: Speaker and forensics endpoints are currently unauthenticated multi-
  tenant (any authenticated caller may submit audio for enrollment). Per-tenant
  isolation for these endpoints is a future work item — documented here.
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
    if not _effective_auth_enabled():
        # Auth disabled (development): still verify the session exists.
        session = session_manager.get(call_id)
        if not session:
            raise HTTPException(status_code=404, detail="Call session not found or expired.")
        return session.caller_id

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
