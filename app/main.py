"""
FastAPI application entrypoint: instantiation, CORS, router registration,
and startup/shutdown hooks (DB init + expired-session cleanup).
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.api.v1 import analyze, call, forensics, speaker, stream, verification
from app.core.session_manager import session_manager
from app.db.database import init_db, SessionLocal
import redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
    session_manager.purge_expired()


app = FastAPI(title=config.APP_NAME, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=config.CORS_ORIGINS != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
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
    # Check database
    try:
        db = SessionLocal()
        db.execute("SELECT 1")
        db.close()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database connection failed: {e}")
    
    # Check Redis if configured for session store
    if config.SESSION_STORE_BACKEND == "redis":
        try:
            r = redis.from_url(config.REDIS_URL)
            r.ping()
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Redis connection failed: {e}")
    
    return {"status": "ready"}
