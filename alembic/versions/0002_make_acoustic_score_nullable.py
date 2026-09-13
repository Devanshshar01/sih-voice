"""Make risk_events.acoustic_score nullable (inference failure support)

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-14 02:10:00.000000

BACKGROUND:
  The ZeroGPU / real inference path may fail (network timeout, HF Space
  unavailable, etc.). When inference fails the pipeline returns
  acoustic_score=None to represent an explicit "inference unavailable" state
  rather than a fabricated score. This is a safety guarantee — the system must
  never return a deterministic/mock score in place of real inference without
  surfacing that fact in every persisted record.

  The original schema had acoustic_score NOT NULL.
  This migration makes it nullable so that NULL records correctly and
  persistently indicate that acoustic inference was unavailable for that window.

SQLite NOTE:
  SQLite does not support ALTER COLUMN. env.py enables Alembic batch mode
  (render_as_batch=True) which performs the safe table-rebuild pattern:
    1. Create a new table with the desired column definition.
    2. Copy all existing rows.
    3. Drop the old table.
    4. Rename the new table.
  This is the standard Alembic approach for SQLite schema alterations and is
  safe on production SQLite databases as long as foreign-key pragmas are set
  (env.py sets PRAGMA foreign_keys=ON).

PostgreSQL NOTE:
  ALTER COLUMN ... DROP NOT NULL is a metadata-only change in PostgreSQL —
  it does not require a table scan or lock escalation for non-indexed columns.
  Alembic batch mode is not invoked for PostgreSQL (env.py only sets
  render_as_batch when the dialect is sqlite).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use batch_alter_table so the statement works on both SQLite (which
    # requires the table-rebuild strategy) and PostgreSQL (which executes a
    # direct ALTER COLUMN statement).
    with op.batch_alter_table("risk_events", schema=None) as batch_op:
        batch_op.alter_column(
            "acoustic_score",
            existing_type=sa.Float(),
            nullable=True,
        )


def downgrade() -> None:
    # WARNING: Downgrading to NOT NULL requires that no NULL values exist in
    # the column. If NULLs are present this will raise an IntegrityError.
    # Callers should ensure the column is clean before downgrading.
    with op.batch_alter_table("risk_events", schema=None) as batch_op:
        batch_op.alter_column(
            "acoustic_score",
            existing_type=sa.Float(),
            nullable=False,
        )
