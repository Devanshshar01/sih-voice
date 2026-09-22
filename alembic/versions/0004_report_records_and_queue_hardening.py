"""Evidence report records + offline anchor queue hardening (integrity phase)

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-20 12:00:00.000000

BACKGROUND:
  Forensic-pipeline hardening adds two durable concerns on top of Phase 10:

    evidence_report_records — one row per Merkle evidence id: the SHA-256 of
      the rendered forensic PDF bytes. The PDF never contains its own hash
      (Phase 7 circularity rule); the digest lives here and is surfaced by the
      verification API. Regeneration replaces the row (unique evidence_id).

    anchor_queue_entries    — three additive columns for retry hardening:
      * idempotency_key  (unique): sha256(root_hash || evidence_id); one
        logical anchor per key, so an ambiguous client timeout is detected
        instead of double-submitting the same root.
      * next_retry_at: earliest permitted next submission (exponential
        backoff); flush only picks entries whose backoff has elapsed.
      * retryable: False once a non-retryable failure (contract revert,
        invalid root) is seen — those entries become PERMANENTLY_FAILED and
        are never retried automatically.

ADDITIVE / NON-DESTRUCTIVE:
  New table + new nullable/optional columns only. No existing column is
  altered or dropped, so previously anchored evidence stays readable and its
  verification path works unchanged. Existing rows get
  idempotency_key = NULL (backfilled lazily on their next queue interaction)
  and retryable = TRUE.

SQLite NOTE:
  ``create_table`` is portable across SQLite and PostgreSQL. The two new
  anchor-queue columns use plain ADD COLUMN (batch mode not required on
  SQLite for pure additions).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # evidence_report_records                                             #
    # ------------------------------------------------------------------ #
    op.create_table(
        "evidence_report_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("evidence_id", sa.String(), nullable=False),
        # sha256 of the rendered PDF bytes (never stored inside the PDF itself).
        sa.Column("report_sha256", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence_merkle_packages.evidence_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evidence_id", name="uq_report_record_evidence"),
    )

    # ------------------------------------------------------------------ #
    # anchor_queue_entries hardening (additive columns)                   #
    # ------------------------------------------------------------------ #
    op.add_column(
        "anchor_queue_entries",
        sa.Column("idempotency_key", sa.String(), nullable=True),
    )
    op.add_column(
        "anchor_queue_entries",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "anchor_queue_entries",
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index(
        "ix_anchor_queue_idempotency", "anchor_queue_entries", ["idempotency_key"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_anchor_queue_idempotency", table_name="anchor_queue_entries")
    op.drop_column("anchor_queue_entries", "retryable")
    op.drop_column("anchor_queue_entries", "next_retry_at")
    op.drop_column("anchor_queue_entries", "idempotency_key")
    op.drop_table("evidence_report_records")
