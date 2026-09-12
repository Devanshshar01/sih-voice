"""
FastAPI application entrypoint: instantiation, middleware stack (request IDs,
rate limiting, CORS), router registration, health/readiness endpoints, and
startup/shutdown hooks (DB init + expired-session cleanup).

Environment modes (VOICETRUST_ENV): development | demo | production.
Production fails fast at import if required configuration is missing
(CORS origins, PostgreSQL database URL, auth keys).
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text as _sqltext

from app import config
from app.api.v1 import analyze, call, forensics, speaker, stream, verification
from app.core.observability import (
    RateLimitMiddleware,
    RequestContextMiddleware,
    configure_logging,
)
from app.core.session_manager import session_manager
from app.db.database import check_db_ready, init_db

configure_logging()
logger = __import__("logging").getLogger("satyavoice")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info(
        "startup complete",
        extra={"mode": config.ENV_MODE, "model_version": config.SPEAKER_MODEL_VERSION},
    )
    yield
    session_manager.purge_expired()


app = FastAPI(title=config.APP_NAME, version="0.1.0", lifespan=lifespan)

# ---- CORS ----
# VOICETRUST_CORS_ORIGINS is a comma-separated origin list. Development/demo
# default to "*" (credentials disabled); production requires explicit origins
# and refuses to boot without them (enforced in config.py).
_credentials_enabled = config.CORS_ORIGINS != ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=_credentials_enabled,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request IDs + structured access logging (outermost, so it wraps everything).
app.add_middleware(RequestContextMiddleware)
# Per-tenant sliding-window rate limiting (no-ops unless enabled).
app.add_middleware(RateLimitMiddleware)


@app.middleware("http")
async def _attach_auth_for_rate_limiting(request, call_next):
    """Resolve the API key early so rate limiting keys on the tenant.

    Runs inside the rate-limit middleware; invalid keys are rejected here
    (before route handlers) with 401, keeping the auth dependency the single
    source of truth for route-level protection.
    """
    from app.core.auth import api_key_auth

    if config.AUTH_REQUIRED:
        try:
            auth = await api_key_auth.__call__(request)
        except Exception as exc:
            status = getattr(exc, "status_code", 500)
            detail = getattr(exc, "detail", "Authentication failed.")
            return Response(
                content=f'{{"detail": "{detail}"}}',
                status_code=status,
                media_type="application/json",
            )
        request.state.auth_context = auth
    return await call_next(request)


@app.on_event("startup")
async def _log_runtime_config() -> None:
    logger.info(
        "CORS enabled origins: %s (credentials=%s) | mode=%s auth=%s session_store=%s",
        config.CORS_ORIGINS,
        _credentials_enabled,
        config.ENV_MODE,
        config.AUTH_REQUIRED,
        config.SESSION_STORE_BACKEND,
    )

app.include_router(call.router, prefix=config.API_V1_PREFIX)
app.include_router(speaker.router, prefix=config.API_V1_PREFIX)
app.include_router(stream.router, prefix=config.API_V1_PREFIX)
app.include_router(verification.router, prefix=config.API_V1_PREFIX)
app.include_router(analyze.router, prefix=config.API_V1_PREFIX)
app.include_router(forensics.router, prefix=config.API_V1_PREFIX)


# ---------------------------------------------------------------------------
# Health / readiness
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check():
    """Liveness: the process is up. Deliberately dependency-free."""
    return {"status": "ok", "service": config.APP_NAME, "mode": config.ENV_MODE}


@app.get("/health/live")
def liveness():
    return {"status": "alive"}


@app.get("/health/ready")
def readiness():
    """Readiness: DB reachable; models loadable; Redis reachable when required."""
    checks: dict = {}
    ok = True

    # Database.
    try:
        checks["database"] = "ready" if check_db_ready() else "not-ready"
        if not check_db_ready():
            ok = False
    except Exception as exc:  # pragma: no cover - defensive
        checks["database"] = f"error: {type(exc).__name__}"
        ok = False

    # AI stack readiness (mock modes are always ready).
    try:
        from app.services.ml_detector import get_detector

        detector = get_detector(
            config.VOICE_DETECTOR_MODE,
            model_path=config.VOICE_MODEL_PATH or None,
            model_id=config.VOICE_MODEL_ID,
            device=config.VOICE_MODEL_DEVICE,
            revision=config.VOICE_MODEL_REVISION,
        )
        status = getattr(detector, "status", None)
        checks["detector"] = status() if callable(status) else "ready"
        if isinstance(checks["detector"], str) and checks["detector"] in {"error", "missing"}:
            ok = False
    except Exception as exc:
        checks["detector"] = f"error: {type(exc).__name__}"
        ok = False

    # Redis: required when the session store is configured as redis-backed.
    if config.SESSION_STORE_BACKEND == "redis":
        try:
            import redis as redis_lib

            redis_lib.Redis.from_url(config.REDIS_URL, decode_responses=True).ping()
            checks["redis"] = "ready"
        except Exception as exc:
            checks["redis"] = f"error: {type(exc).__name__}"
            ok = False
    else:
        checks["redis"] = "not-required"

    return Response(
        content=__import__("json").dumps(
            {"status": "ready" if ok else "not-ready", "checks": checks}
        ),
        status_code=200 if ok else 503,
        media_type="application/json",
    )
