"""
FastAPI application entrypoint: instantiation, CORS, router registration,
and startup/shutdown hooks (DB init + expired-session cleanup).
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.api.v1 import analyze, call, forensics, speaker, stream, verification
from app.core.session_manager import session_manager
from app.db.database import init_db, SessionLocal
import redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging
    _lifespan_logger = logging.getLogger("satyavoice")
    # Enforce production safety policy before serving any traffic
    config.validate_detector_config()
    # B9: Warn if running in production with wildcard CORS (security risk)
    if config.IS_PRODUCTION and config.CORS_ORIGINS == ["*"]:
        _lifespan_logger.warning(
            "SECURITY WARNING: CORS is set to '*' in production. "
            "Set VOICETRUST_CORS_ORIGINS to the exact Vercel frontend origin "
            "(e.g. https://satyavoice.vercel.app) to enforce browser origin policy."
        )
    init_db()
    yield
    session_manager.purge_expired()


app = FastAPI(title=config.APP_NAME, version="0.1.0", lifespan=lifespan)

# CORS: VOICETRUST_CORS_ORIGINS is a comma-separated origin list. The default
# "*" keeps local demos friction-free; production deployments should set it to
# the exact frontend origin (e.g. https://satyavoice.vercel.app) — wildcard
# origins cannot be combined with credentials.
_credentials_enabled = config.CORS_ORIGINS != ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=_credentials_enabled,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _log_startup_config() -> None:
    import logging

    logger = logging.getLogger("satyavoice")
    logger.info(
        "CORS enabled origins: %s (credentials=%s)",
        config.CORS_ORIGINS,
        _credentials_enabled,
    )
    logger.info("Environment: %s", config.ENVIRONMENT)
    logger.info("Selected detector mode: %s", config.VOICE_DETECTOR_MODE)
    logger.info(
        "Mock detector: %s",
        "DISABLED" if config.IS_PRODUCTION or config.VOICE_DETECTOR_MODE != "mock" else "ENABLED (development opt-in)"
    )
    logger.info(
        "ZeroGPU Space status: %s",
        "CONFIGURED" if bool(config.HF_ZERO_GPU_SPACE) else "NOT_CONFIGURED"
    )

app.include_router(call.router, prefix=config.API_V1_PREFIX)
app.include_router(speaker.router, prefix=config.API_V1_PREFIX)
app.include_router(stream.router, prefix=config.API_V1_PREFIX)
app.include_router(verification.router, prefix=config.API_V1_PREFIX)
app.include_router(analyze.router, prefix=config.API_V1_PREFIX)
app.include_router(forensics.router, prefix=config.API_V1_PREFIX)


@app.get("/health")
def health_check():
    return {"status": "ok", "service": config.APP_NAME}


@app.get("/ready")
def readiness_check():
    # Check production safety validation & provider configuration
    try:
        config.validate_detector_config()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Detector configuration invalid: {e}")

    # Check database, but do not fail readiness if the DB is temporarily
    # unavailable. The stream and call endpoints already degrade gracefully
    # when persistence is unavailable, so readiness should reflect service
    # health rather than forcing a hard crash on an optional backing store.
    db_status = "not_checked"
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        db_status = "available"
    except Exception as e:
        db_status = "unavailable"
        logging.getLogger("satyavoice").warning(
            "Database probe failed during readiness check; continuing in degraded mode. %s",
            e,
        )

    # Check Redis if configured for session store, but do not fail readiness
    # when Redis is unavailable. The session manager already falls back to
    # in-memory sessions, so the backend should continue serving traffic.
    redis_status = "not_configured"
    if config.SESSION_STORE_BACKEND == "redis":
        logger = logging.getLogger("satyavoice")
        try:
            redis_client = getattr(session_manager, "_redis_client", None)
            if redis_client is None:
                raise RuntimeError("Redis client not initialized")
            redis_client.ping()
            redis_status = "available"
        except Exception as e:
            redis_status = "unavailable_fallback_to_memory"
            logger.warning(
                "Redis session store unavailable; continuing with in-memory fallback. %s",
                e,
            )

    return {
        "status": "ready",
        "environment": config.ENVIRONMENT,
        "detector_mode": config.VOICE_DETECTOR_MODE,
        "mock_disabled": config.IS_PRODUCTION or config.VOICE_DETECTOR_MODE != "mock",
        "session_store_backend": config.SESSION_STORE_BACKEND,
        "database_status": db_status,
        "redis_status": redis_status,
    }

