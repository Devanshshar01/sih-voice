"""
SQLite connection setup.

Active call state (ring buffers, live risk timeline) lives in memory --
see core/session_manager.py. This module only persists the durable,
post-call audit trail: derived scores and events, never raw audio.
"""
from sqlalchemy import create_engine, text as _sqltext
from sqlalchemy.orm import sessionmaker, declarative_base

from app import config

connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db() -> None:
    """Create tables and apply versioned migrations. Called once on app startup."""
    from app.db import models  # noqa: F401  (ensures models are registered on Base)
    Base.metadata.create_all(bind=engine)
    from app.db.migrations import run_migrations
    run_migrations()


def get_db():
    """FastAPI dependency that yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_ready() -> bool:
    """Lightweight readiness probe (SELECT 1). Never raises."""
    try:
        with engine.connect() as conn:
            conn.execute(_sqltext("SELECT 1"))
        return True
    except Exception:
        return False
