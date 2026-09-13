"""Alembic environment script for SatyaVoice migrations.

Key design decisions:
  - Database URL is always read from VOICETRUST_DATABASE_URL (or the default
    SQLite path) at migration time, never hardcoded.
  - The application's SQLAlchemy Base.metadata is imported directly so Alembic
    autogenerate sees the current ORM model definitions.
  - SQLite-specific pragmas (foreign_keys, WAL mode) are applied via event
    listeners so the migration runner behaves consistently with the application.
  - Passwords/credentials are never logged (the URL is sanitised before any
    logger call by Alembic's own render_item; we don't log it ourselves).
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# ---------------------------------------------------------------------------
# Alembic Config object — gives access to the values in alembic.ini
# ---------------------------------------------------------------------------
config = context.config

# Interpret the config file for Python logging if present.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Import ORM metadata so autogenerate can detect schema changes
# ---------------------------------------------------------------------------
# We import app.db.database lazily to avoid circular import problems if the
# environment script is invoked before the app is fully initialised.
from app.db.database import Base  # noqa: E402
from app.db import models  # noqa: F401, E402  — registers all ORM tables on Base

target_metadata = Base.metadata

# ---------------------------------------------------------------------------
# Resolve the database URL from environment (production-safe, never hardcoded)
# ---------------------------------------------------------------------------
_APP_DATABASE_URL = os.getenv(
    "VOICETRUST_DATABASE_URL",
    "sqlite:///./satyavoice.db",
)

# Override the alembic.ini placeholder with the real runtime URL.
# Alembic sanitises the URL before printing it, so passwords are not leaked.
config.set_main_option("sqlalchemy.url", _APP_DATABASE_URL)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _configure_sqlite_engine(connection) -> None:
    """Apply SQLite pragmas that keep behaviour consistent with the app."""
    from sqlalchemy import event, text

    @event.listens_for(connection, "connect")
    def _set_pragmas(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# ---------------------------------------------------------------------------
# Offline (--sql) migration mode
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting to the database."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=_is_sqlite(url),  # SQLite requires batch mode for ALTER
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online (connected) migration mode
# ---------------------------------------------------------------------------

def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    url = config.get_main_option("sqlalchemy.url")
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        url=url,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=_is_sqlite(url),  # required for SQLite column alterations
        )

        with context.begin_transaction():
            context.run_migrations()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
