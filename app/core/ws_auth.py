"""
WebSocket authentication and authorization for SatyaVoice.

Design constraints:
  - Browsers cannot set custom headers for WebSocket handshakes, so the JWT
    is passed as a query parameter: ?token=<jwt>
  - PyJWT (already in requirements.txt) is used for token validation.
  - Secret is drawn from the environment only, never from source code.
  - Ownership check: the authenticated principal (JWT ``sub``) must match
    the ``caller_id`` stored in the server-side CallSession — this prevents
    IDOR/BOLA where an attacker changes only the call_id path param.
  - Development bypass: when VOICETRUST_WS_AUTH_ENABLED=false the checks
    are skipped. This value is never allowed to be false in production
    (IS_PRODUCTION guard).

Public surface:
  authenticate_websocket(websocket, call_id) -> None
      Reads the token query param, validates it, checks session ownership,
      and closes the WebSocket with an appropriate code on any failure.
      Raises nothing; caller should return immediately after a failure.

  create_access_token(subject, expires_delta) -> str
      Convenience helper used only in tests to mint short-lived tokens.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import timedelta
from typing import Optional

import jwt
from fastapi import WebSocket

from app.core.session_manager import session_manager

logger = logging.getLogger("satyavoice.ws_auth")

# --------------------------------------------------------------------------
# Configuration -- all read from environment, nothing hard-coded.
# --------------------------------------------------------------------------

# F6A: there is NO hardcoded fallback secret. A fixed, publicly known default
# would let anyone mint valid tokens for any call. The secret comes from
# VOICETRUST_WS_JWT_SECRET only:
#   * production: a missing (or known-demo) secret is REJECTED at startup by
#     validate_ws_auth_config() and fails closed in _get_secret() on every
#     token operation.
#   * development: a missing secret falls back to a per-process RANDOM
#     development secret (unguessable, invalid across restarts) so local
#     flows keep working without shipping a demo secret.
_WS_JWT_SECRET: str = (os.getenv("VOICETRUST_WS_JWT_SECRET") or "").strip()
_WS_JWT_ALGORITHM: str = os.getenv("VOICETRUST_WS_JWT_ALGORITHM", "HS256")
_WS_JWT_EXPIRY_SECONDS: int = int(os.getenv("VOICETRUST_WS_JWT_EXPIRY_SECONDS", "3600"))

# Values that previously shipped as demo defaults and must never be accepted
# as a production signing secret.
_FORBIDDEN_WEAK_SECRETS = frozenset(
    {
        "sih-demo-fallback-secret-2026",
        "changeme",
        "secret",
        "test-secret",
    }
)

# Lazily created per-process development secret (never used in production).
_DEV_SECRET: Optional[str] = None

# Auth bypass for development ONLY (never allowed in production).
_WS_AUTH_ENABLED_RAW: str = os.getenv("VOICETRUST_WS_AUTH_ENABLED", "true").lower().strip()
_WS_AUTH_ENABLED: bool = _WS_AUTH_ENABLED_RAW not in {"0", "false", "no", "off"}

# --------------------------------------------------------------------------
# WebSocket close codes used by this module
# --------------------------------------------------------------------------
WS_CLOSE_POLICY_VIOLATION = 4001  # missing / invalid / expired token
WS_CLOSE_FORBIDDEN = 4003         # valid token, wrong session ownership


def _effective_auth_enabled() -> bool:
    """Compute whether auth is active, re-reading ENVIRONMENT at call time.

    Production environments always enforce auth regardless of the env var.
    """
    from app import config  # local import to avoid circular dependency

    if config.IS_PRODUCTION:
        return True
    return _WS_AUTH_ENABLED


def _development_secret() -> str:
    """Per-process random development secret (never a fixed demo string)."""
    global _DEV_SECRET
    if _DEV_SECRET is None:
        import secrets

        _DEV_SECRET = secrets.token_hex(32)
    return _DEV_SECRET


def _get_secret() -> str:
    """Return the signing secret for the current environment.

    Resolution order: live environment variable -> import-time snapshot ->
    (non-production only) ephemeral per-process development secret.
    Production with no configured secret raises RuntimeError (fail closed):
    tokens are never signed or verified with an insecure default.
    """
    secret = (os.getenv("VOICETRUST_WS_JWT_SECRET") or "").strip() or _WS_JWT_SECRET
    if secret:
        return secret
    from app import config  # local import to avoid circular dependency

    if config.IS_PRODUCTION:
        raise RuntimeError(
            "VOICETRUST_WS_JWT_SECRET is not configured. Production refuses "
            "to fall back to an insecure default JWT secret; set a strong "
            "random value (e.g. `openssl rand -hex 32`) before serving traffic."
        )
    return _development_secret()


def validate_ws_auth_config() -> None:
    """Startup gate (called from the app lifespan): production must have an
    explicitly configured JWT secret. Raises RuntimeError otherwise.

    Development is lenient: the per-process development secret is used and no
    exception is raised.
    """
    from app import config  # local import to avoid circular dependency

    if not config.IS_PRODUCTION:
        return
    secret = (os.getenv("VOICETRUST_WS_JWT_SECRET") or "").strip() or _WS_JWT_SECRET
    if not secret:
        raise RuntimeError(
            "PRODUCTION ENVIRONMENT SAFETY VIOLATION: "
            "VOICETRUST_WS_JWT_SECRET must be set in production; refusing to "
            "fall back to an insecure default JWT secret."
        )
    if secret in _FORBIDDEN_WEAK_SECRETS:
        raise RuntimeError(
            "PRODUCTION ENVIRONMENT SAFETY VIOLATION: "
            "VOICETRUST_WS_JWT_SECRET is a known public/demo value; set a "
            "strong random secret instead."
        )


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    """Mint a short-lived JWT for the given subject.

    Used in tests and (optionally) by a future /auth/token REST endpoint.
    The secret MUST be configured; this will raise ValueError if it is not.
    """
    secret = _get_secret()
    if not secret:
        raise ValueError(
            "VOICETRUST_WS_JWT_SECRET is not configured. "
            "Set it in the environment before creating tokens."
        )
    delta = expires_delta if expires_delta is not None else timedelta(seconds=_WS_JWT_EXPIRY_SECONDS)
    now = int(time.time())
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + int(delta.total_seconds()),
    }
    return jwt.encode(payload, secret, algorithm=_WS_JWT_ALGORITHM)


def _validate_token(raw_token: str) -> Optional[str]:
    """Validate the JWT and return the ``sub`` claim on success, or None.

    Never logs the raw token; only logs the error class. Fails closed when the
    signing secret is unavailable (production without a configured secret).
    """
    try:
        secret = _get_secret()
    except RuntimeError as exc:
        logger.error("ws_auth: token validation unavailable — %s", exc)
        return None
    if not secret:
        logger.warning("ws_auth: token validation attempted but secret is not configured")
        return None
    try:
        payload = jwt.decode(raw_token, secret, algorithms=[_WS_JWT_ALGORITHM])
        sub = payload.get("sub")
        if not sub or not isinstance(sub, str):
            logger.warning("ws_auth: token missing or non-string 'sub' claim")
            return None
        return sub
    except jwt.ExpiredSignatureError:
        logger.info("ws_auth: token rejected — expired")
        return None
    except jwt.InvalidTokenError as exc:
        logger.info("ws_auth: token rejected — %s", type(exc).__name__)
        return None


async def authenticate_websocket(websocket: WebSocket, call_id: str) -> bool:
    """Authenticate and authorize an incoming WebSocket connection.

    Returns True if the connection is allowed, False if it was rejected.
    On rejection the WebSocket is closed with an appropriate code before
    returning; the caller MUST return immediately (not call accept()).

    Authorization contract:
      1. Token must be present in ?token= query param.
      2. Token must be a valid, non-expired JWT signed with our secret.
      3. JWT ``sub`` claim must match the ``caller_id`` stored in the
         server-side CallSession for call_id (prevents IDOR/BOLA).
    """
    if not _effective_auth_enabled():
        # Development bypass: auth disabled — still validate the session
        # exists (a 4404 close is better than a crash).
        session = session_manager.get(call_id)
        if not session:
            logger.info("ws_auth: call_id=%s not found (auth disabled)", call_id)
            await websocket.close(code=4404)
            return False
        logger.debug("ws_auth: auth disabled, skipping token check for call_id=%s", call_id)
        return True

    # --- Step 1: Extract token from query params ---
    raw_token: Optional[str] = websocket.query_params.get("token")
    if not raw_token:
        logger.info("ws_auth: rejected — missing token (call_id=%s)", call_id)
        await websocket.close(code=WS_CLOSE_POLICY_VIOLATION)
        return False

    # --- Step 2: Validate token cryptographically ---
    subject = _validate_token(raw_token)
    if subject is None:
        logger.info("ws_auth: rejected — invalid/expired token (call_id=%s)", call_id)
        await websocket.close(code=WS_CLOSE_POLICY_VIOLATION)
        return False

    # --- Step 3: Resolve call session (must exist on the server) ---
    session = session_manager.get(call_id)
    if not session:
        logger.info(
            "ws_auth: rejected — call_id=%s not found (subject=<redacted>)", call_id
        )
        await websocket.close(code=4404)
        return False

    # --- Step 4: Ownership check — subject must be the call's caller ---
    if session.caller_id != subject:
        logger.warning(
            "ws_auth: IDOR attempt — authenticated subject does not own call_id=%s",
            call_id,
        )
        await websocket.close(code=WS_CLOSE_FORBIDDEN)
        return False

    logger.debug("ws_auth: accepted subject for call_id=%s", call_id)
    return True
