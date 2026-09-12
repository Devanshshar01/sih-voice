"""API-key authentication and tenant boundaries.

Model: each tenant/user is provisioned an API key via the
``VOICETRUST_AUTH_API_KEYS`` env var ("tenant_id:key" pairs, comma-separated).
The key never grants cross-tenant access: the tenant id is derived from the
presented key, never from client-supplied fields, so one tenant cannot read or
write another tenant's enrollment/match results.

Development/demo: with no keys configured, auth is OPEN (all requests share
the "default" tenant) so the SIH demo flow keeps working unchanged.
Production: keys are REQUIRED; the app refuses to boot without them.
"""
from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from app import config

logger = logging.getLogger("satyavoice.auth")

_header_scheme = APIKeyHeader(name=config.AUTH_HEADER, auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    tenant_id: str
    key_name: str  # which key identity authenticated (never the key itself)


class ApiKeyAuth:
    def __init__(self) -> None:
        self._keys: dict[str, str] = {}
        self._parse_keys()

    def _parse_keys(self) -> None:
        raw = config.AUTH_API_KEYS.strip()
        if not raw:
            return
        for pair in raw.split(","):
            pair = pair.strip()
            if not pair or ":" not in pair:
                logger.warning("Ignoring malformed auth entry (expected tenant:key): %r", pair.split(":")[0] + ":***")
                continue
            tenant, key = pair.split(":", 1)
            tenant, key = tenant.strip(), key.strip()
            if tenant and key:
                self._keys[key] = tenant

    # ------------------------------------------------------------------
    def tenant_for_key(self, key: str) -> Optional[str]:
        # Constant-time comparison across all configured keys.
        for candidate, tenant in self._keys.items():
            if secrets.compare_digest(candidate, key):
                return tenant
        return None

    @property
    def enabled(self) -> bool:
        return config.AUTH_REQUIRED

    async def __call__(self, request: Request) -> AuthContext:
        """FastAPI dependency: resolve the caller's tenant from the API key."""
        if not config.AUTH_REQUIRED:
            return AuthContext(tenant_id="default", key_name="anonymous")

        key = await _header_scheme(request)
        if not key:
            raise HTTPException(
                status_code=401,
                detail=f"Missing {config.AUTH_HEADER} header.",
                headers={"WWW-Authenticate": "ApiKey"},
            )
        tenant = self.tenant_for_key(key)
        if tenant is None:
            raise HTTPException(status_code=401, detail="Invalid API key.")
        return AuthContext(tenant_id=tenant, key_name=f"key-{hash(key) % 10000:04d}")


# Module-level singleton used by routers via ``Depends(require_auth)``.
api_key_auth = ApiKeyAuth()

# Convenience alias for router dependencies.
require_auth = api_key_auth
