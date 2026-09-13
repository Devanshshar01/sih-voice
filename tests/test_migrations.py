"""Tests for Alembic database migrations."""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.models import Session as DbSession


@pytest.fixture
def temp_db_url():
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_migrations.db"
        url = f"sqlite:///{db_path}"
        os.environ["VOICETRUST_DATABASE_URL"] = url
        yield url
        if "VOICETRUST_DATABASE_URL" in os.environ:
            del os.environ["VOICETRUST_DATABASE_URL"]


@pytest.fixture
def alembic_config(temp_db_url):
    ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    cfg = Config(str(ini_path))
    # env.py reads VOICETRUST_DATABASE_URL, so we don't strictly need to set it here,
    # but it doesn't hurt.
    cfg.set_main_option("sqlalchemy.url", temp_db_url)
    return cfg


def test_migrations_up_to_head_and_acoustic_score_nullable(alembic_config, temp_db_url):
    """Test that migrations can initialize a fresh DB and that acoustic_score is nullable."""
    # 1. Run migrations to head
    command.upgrade(alembic_config, "head")

    # 2. Inspect the resulting schema
    engine = create_engine(temp_db_url)
    inspector = inspect(engine)

    # Check tables exist
    tables = inspector.get_table_names()
    assert "sessions" in tables
    assert "risk_events" in tables
    assert "speaker_identities" in tables
    assert "evidence_packages" in tables

    # Check acoustic_score nullability
    columns = {col["name"]: col for col in inspector.get_columns("risk_events")}
    assert "acoustic_score" in columns
    assert columns["acoustic_score"]["nullable"] is True

    # 3. Insert a record with NULL acoustic_score (should succeed)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sessions (call_id, caller_id, recipient_id, status, max_risk_score) "
                "VALUES ('test-call', 'caller1', 'recip1', 'ACTIVE', 0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO risk_events (call_id, intent_score, combined_risk_score, acoustic_score) "
                "VALUES ('test-call', 0.5, 50, NULL)"
            )
        )
        
        result = conn.execute(text("SELECT acoustic_score FROM risk_events")).scalar()
        assert result is None
    
    # Dispose of engine to release SQLite file lock on Windows
    engine.dispose()


def test_migration_0001_to_0002_upgrade(alembic_config, temp_db_url):
    """Test upgrading from 0001 to 0002 changes nullability."""
    # 1. Upgrade to 0001
    command.upgrade(alembic_config, "0001")

    engine = create_engine(temp_db_url)
    inspector = inspect(engine)
    
    # In 0001, acoustic_score should be NOT NULL
    columns = {col["name"]: col for col in inspector.get_columns("risk_events")}
    assert columns["acoustic_score"]["nullable"] is False

    # 2. Upgrade to 0002
    command.upgrade(alembic_config, "0002")

    # Clear inspector cache
    inspector = inspect(engine)
    
    # In 0002, acoustic_score should be nullable
    columns = {col["name"]: col for col in inspector.get_columns("risk_events")}
    assert columns["acoustic_score"]["nullable"] is True
    
    engine.dispose()
