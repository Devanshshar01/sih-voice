"""Initial schema: all SatyaVoice tables (sessions, risk_events, speaker vault, evidence)

Revision ID: 0001
Revises:
Create Date: 2026-09-14 02:00:00.000000

This migration creates the complete initial schema as defined in app/db/models.py.
It represents the state of the database before Alembic was introduced.

NOTES:
  - acoustic_score is initially created as NOT NULL (matching the original
    schema before the Phase 7 fix). Migration 0002 relaxes this constraint.
  - SQLite batch mode is used automatically by env.py for ALTER TABLE operations.
  - All tables include their primary keys, foreign keys, indexes, and check
    constraints exactly as defined in the ORM models.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # sessions                                                             #
    # ------------------------------------------------------------------ #
    op.create_table(
        "sessions",
        sa.Column("call_id", sa.String(), nullable=False),
        sa.Column("caller_id", sa.String(), nullable=False),
        sa.Column("recipient_id", sa.String(), nullable=False),
        sa.Column(
            "start_time",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("max_risk_score", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('ACTIVE','COMPLETED','TERMINATED_RISK')",
            name="ck_session_status",
        ),
        sa.PrimaryKeyConstraint("call_id"),
    )

    # ------------------------------------------------------------------ #
    # risk_events                                                          #
    # ------------------------------------------------------------------ #
    op.create_table(
        "risk_events",
        sa.Column("event_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("call_id", sa.String(), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        # NOTE: acoustic_score is NOT NULL here (original schema).
        # Migration 0002 makes it nullable to represent inference failures.
        sa.Column("acoustic_score", sa.Float(), nullable=False),
        sa.Column("intent_score", sa.Float(), nullable=False),
        sa.Column("combined_risk_score", sa.Integer(), nullable=False),
        sa.Column("triggered_rule", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["call_id"],
            ["sessions.call_id"],
        ),
        sa.PrimaryKeyConstraint("event_id"),
    )

    # ------------------------------------------------------------------ #
    # speaker_identities                                                   #
    # ------------------------------------------------------------------ #
    op.create_table(
        "speaker_identities",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("speaker_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("model_identifier", sa.String(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("normalization", sa.String(), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("centroid_embedding", sa.LargeBinary(), nullable=False),
        sa.Column("enrollment_sample_count", sa.Integer(), nullable=False),
        sa.Column("enrollment_version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_speaker_identity",
        "speaker_identities",
        ["tenant_id", "speaker_id"],
        unique=True,
    )
    op.create_index(
        "ix_speaker_identity_active",
        "speaker_identities",
        ["is_active"],
    )

    # ------------------------------------------------------------------ #
    # speaker_enrollment_samples                                           #
    # ------------------------------------------------------------------ #
    op.create_table(
        "speaker_enrollment_samples",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("identity_id", sa.Integer(), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("rms", sa.Float(), nullable=True),
        sa.Column("peak", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["speaker_identities.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_speaker_sample_identity",
        "speaker_enrollment_samples",
        ["identity_id", "is_active"],
    )

    # ------------------------------------------------------------------ #
    # evidence_packages                                                    #
    # ------------------------------------------------------------------ #
    op.create_table(
        "evidence_packages",
        sa.Column("evidence_id", sa.String(), nullable=False),
        sa.Column("evidence_hash", sa.String(), nullable=False),
        sa.Column("evidence_digest", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("package_format", sa.String(), nullable=False),
        sa.Column("package_payload", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("local_chain_root", sa.String(), nullable=True),
        sa.Column("local_chain_status", sa.String(), nullable=False),
        sa.Column("blockchain_network", sa.String(), nullable=True),
        sa.Column("contract_address", sa.String(), nullable=True),
        sa.Column("anchor_tx_hash", sa.String(), nullable=True),
        sa.Column("anchor_block_number", sa.Integer(), nullable=True),
        sa.Column("anchor_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("anchor_status", sa.String(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("evidence_id"),
        sa.UniqueConstraint("evidence_hash"),
    )

    # ------------------------------------------------------------------ #
    # evidence_ledger_records                                              #
    # ------------------------------------------------------------------ #
    op.create_table(
        "evidence_ledger_records",
        sa.Column("record_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("evidence_id", sa.String(), nullable=False),
        sa.Column("record_hash", sa.String(), nullable=False),
        sa.Column("previous_record_hash", sa.String(), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("evidence_digest", sa.String(), nullable=False),
        sa.Column("chain_root_hash", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence_packages.evidence_id"],
        ),
        sa.PrimaryKeyConstraint("record_id"),
    )

    # ------------------------------------------------------------------ #
    # evidence_anchors                                                     #
    # ------------------------------------------------------------------ #
    op.create_table(
        "evidence_anchors",
        sa.Column("anchor_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("evidence_id", sa.String(), nullable=False),
        sa.Column("root_hash", sa.String(), nullable=False),
        sa.Column("blockchain_network", sa.String(), nullable=False),
        sa.Column("contract_address", sa.String(), nullable=True),
        sa.Column("tx_hash", sa.String(), nullable=True),
        sa.Column("block_number", sa.Integer(), nullable=True),
        sa.Column("anchor_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence_packages.evidence_id"],
        ),
        sa.PrimaryKeyConstraint("anchor_id"),
    )


def downgrade() -> None:
    # Drop in reverse dependency order.
    op.drop_table("evidence_anchors")
    op.drop_table("evidence_ledger_records")
    op.drop_table("evidence_packages")
    op.drop_index("ix_speaker_sample_identity", table_name="speaker_enrollment_samples")
    op.drop_table("speaker_enrollment_samples")
    op.drop_index("ix_speaker_identity_active", table_name="speaker_identities")
    op.drop_index("uq_speaker_identity", table_name="speaker_identities")
    op.drop_table("speaker_identities")
    op.drop_table("risk_events")
    op.drop_table("sessions")
