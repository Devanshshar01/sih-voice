"""
SQLAlchemy engine, session factory, and database initialization.

PRODUCTION SCHEMA MANAGEMENT:
  Schema evolution in production is handled by Alembic migrations, NOT by
  Base.metadata.create_all(). The correct deployment workflow is:

      alembic upgrade head

  See DATABASE_MIGRATIONS.md for the full deployment guide.

LOCAL DEVELOPMENT / TESTS:
  create_all() is called only when VOICETRUST_DB_CREATE_ALL=true (the default
  for local SQLite environments). This allows a disposable local database to
  bootstrap without running Alembic. It is NOT the production mechanism.

CREDENTIAL SAFETY:
  The DATABASE_URL is sourced exclusively from the VOICETRUST_DATABASE_URL
  environment variable. It is never hardcoded and is not logged in full
  (passwords are redacted before any log emission).

Active call state (ring buffers, live risk timeline) lives in memory --
see core/session_manager.py. This module persists only the durable,
post-call audit trail: derived scores and events, never raw audio.
"""
from __future__ import annotations

import logging
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app import config

logger = logging.getLogger("satyavoice.db")

# ---------------------------------------------------------------------------
# Engine / Session
# ---------------------------------------------------------------------------

connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ---------------------------------------------------------------------------
# Schema initialization
# ---------------------------------------------------------------------------

def _log_safe_db_url(url: str) -> str:
    """Return the URL with any password component replaced by ***."""
    try:
        from sqlalchemy.engine import make_url
        return repr(make_url(url).render_as_string(hide_password=True))
    except Exception:
        # Fallback: strip anything between :// and @ that looks like credentials
        import re
        return re.sub(r"://([^@]*)@", "://***@", url)


def init_db() -> None:
    """Initialize the database for application startup.

    PRODUCTION:
      This function does NOT run Alembic migrations. In production, run:
          alembic upgrade head
      before starting the application.

    DEVELOPMENT / TESTS:
      When VOICETRUST_DB_CREATE_ALL=true (the default for SQLite environments),
      this function calls create_all() to bootstrap a disposable local database.
      This is NOT a substitute for proper Alembic migrations.
    """
    from app.db import models  # noqa: F401  (registers all ORM models on Base)

    db_url = config.DATABASE_URL
    is_sqlite = db_url.startswith("sqlite")

    # Determine whether to run create_all (local dev / test only).
    _create_all_raw = os.getenv("VOICETRUST_DB_CREATE_ALL", "true" if is_sqlite else "false")
    _create_all = _create_all_raw.lower().strip() in {"1", "true", "yes", "on"}

    if config.IS_PRODUCTION and _create_all:
        logger.warning(
            "VOICETRUST_DB_CREATE_ALL=true in production is not recommended. "
            "Use 'alembic upgrade head' for schema management. "
            "Proceeding with create_all() for compatibility — this will NOT "
            "apply pending Alembic migrations."
        )

    if _create_all:
        Base.metadata.create_all(bind=engine)
        logger.debug(
            "create_all() completed for %s (dev/test mode — not a production migration)",
            _log_safe_db_url(db_url),
        )
    else:
        logger.info(
            "VOICETRUST_DB_CREATE_ALL=false — skipping create_all(). "
            "Ensure 'alembic upgrade head' has been run before starting the application."
        )

    # Run the legacy hand-rolled migrations (for pre-Alembic schema history
    # on existing databases). New schema changes must go through Alembic.
    try:
        from app.db.migrations import run_migrations
        applied = run_migrations()
        if applied:
            logger.info("Applied %d legacy migration(s).", applied)
    except Exception as exc:
        logger.warning("Legacy migration runner encountered an error: %s", exc)


def get_db():
    """FastAPI dependency that yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
