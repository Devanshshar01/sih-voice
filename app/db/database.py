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
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.orm import sessionmaker, declarative_base

from app import config

logger = logging.getLogger("satyavoice.db")

# ---------------------------------------------------------------------------
# Engine / Session
# ---------------------------------------------------------------------------

connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
# Production-safe pooling (managed PostgreSQL such as Render closes idle
# connections server-side):
#   - pool_pre_ping: transparently discard dead pooled connections instead of
#     raising "SSL connection has been closed unexpectedly" on first use.
#   - pool_recycle: bound connection age below the server's idle timeout so
#     long-lived Render workers never sit on a stale socket.
engine = create_engine(
    config.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    pool_recycle=300,  # seconds; Render's Postgres idle cutoff is ~5 minutes
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ---------------------------------------------------------------------------
# Connection-loss recovery
# ---------------------------------------------------------------------------
# Managed PostgreSQL (Render, RDS, Cloud SQL) closes idle connections server
# side. The socket can be dead by the time SQLAlchemy checks it out, which
# surfaces as `OperationalError: SSL connection has been closed unexpectedly`.
# These helpers reacquire a healthy connection instead of failing forever on
# the same broken socket.

_DISCONNECT_MARKERS = (
    "ssl connection has been closed",
    "connection has been closed",
    "server closed the connection",
    "connection reset",
    "connection already closed",
    "connection refused",
    "terminating connection",
    "could not receive data",
    "eof detected",
    "broken pipe",
    "gone away",
)


def is_transient_disconnect(exc: BaseException) -> bool:
    """True when ``exc`` looks like a dropped/closed connection (retryable)."""
    if isinstance(exc, InterfaceError):
        return True
    if isinstance(exc, DBAPIError) and getattr(exc, "connection_invalidated", False):
        return True
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in text for marker in _DISCONNECT_MARKERS)


def dispose_engine_pool() -> None:
    """Drop every pooled connection so the next checkout is brand new."""
    try:
        engine.dispose()
    except Exception:  # pragma: no cover - defensive
        logger.warning("engine.dispose() failed during DB recovery", exc_info=True)


def commit_with_retry(db, redo=None, *, attempts: int = 2, context: str = "db.commit") -> bool:
    """Commit ``db``, recovering from a transiently closed connection.

    On ANY commit failure the session is rolled back first -- a session whose
    commit failed must never be reused -- and the pooled connections are
    disposed so the next checkout cannot hand back the dead socket.

    A single bounded retry happens only when the error looks like a dropped
    connection AND the caller supplied ``redo`` to re-stage the work.
    Non-transient errors (constraint violations, programming errors) are never
    retried.

    Returns True on success. On failure the original exception is logged with a
    traceback and False is returned, so callers must choose their own failure
    semantics (e.g. HTTP 503) instead of treating the write as successful.
    """
    total = max(1, attempts)
    attempt = 0
    while attempt < total:
        attempt += 1
        try:
            db.commit()
            return True
        except Exception as exc:
            # Never keep using a failed session.
            try:
                db.rollback()
            except Exception:  # pragma: no cover - rollback on a dead session
                logger.debug("rollback failed after commit error", exc_info=True)
            dispose_engine_pool()

            retryable = redo is not None and is_transient_disconnect(exc)
            if retryable and attempt < total:
                logger.warning(
                    "%s failed on attempt %d/%d (%s) — reacquiring a fresh "
                    "connection and retrying",
                    context,
                    attempt,
                    total,
                    type(exc).__name__,
                )
                try:
                    redo()
                except Exception:
                    logger.error("%s re-stage failed; aborting retry", context, exc_info=True)
                    return False
                continue

            logger.error("%s failed (%s): %s", context, type(exc).__name__, exc, exc_info=True)
            return False
    return False


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
    """FastAPI dependency that yields a DB session and always closes it.

    A request handler that raises leaves an open transaction behind; rolling it
    back explicitly returns the connection to the pool in a clean state instead
    of leaking a poisoned session into the next checkout.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        try:
            db.rollback()
        except Exception:  # pragma: no cover - session may already be dead
            logger.debug("rollback failed while closing request session", exc_info=True)
        raise
    finally:
        db.close()



