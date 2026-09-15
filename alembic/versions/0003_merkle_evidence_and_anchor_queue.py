"""Merkle evidence packages + offline anchor queue (Phase 10)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-15 12:00:00.000000

BACKGROUND:
  Phase 10 introduces a Merkle-root anchoring scheme on top of the existing
  flat evidence ledger. Two new concerns need durable storage:

    evidence_merkle_packages — one row per Merkle evidence package: the RFC 8785
      canonical manifest, its package hash, the 32-byte Merkle root, and the
      on-chain anchor metadata (network/contract/tx/block/status).

    evidence_merkle_leaves   — one row per named evidence item: the per-item
      SHA-256, the domain-separated leaf hash, and a cached inclusion proof.

    anchor_queue_entries     — the offline anchor queue. When a device is
      offline (rural/edge deployment) a computed root is queued here and later
      submitted when connectivity returns. Lifecycle: OFFLINE → PENDING →
      CONFIRMED / FAILED.

ADDITIVE / NON-DESTRUCTIVE:
  These are brand-new tables. No existing column is altered, so previously
  anchored evidence (evidence_packages / evidence_ledger_records) is untouched
  and its verification path keeps working unchanged.

SQLite NOTE:
  ``create_table`` is portable across SQLite and PostgreSQL; no batch mode is
  required because nothing existing is modified.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # evidence_merkle_packages                                             #
    # ------------------------------------------------------------------ #
    op.create_table(
        "evidence_merkle_packages",
        sa.Column("evidence_id", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("package_format", sa.String(), nullable=False),
        sa.Column("canonical_package", sa.Text(), nullable=False),
        sa.Column("package_hash", sa.String(), nullable=False),
        sa.Column("merkle_root", sa.String(), nullable=False),
        sa.Column("leaf_count", sa.Integer(), nullable=False),
        sa.Column("leaves_json", sa.Text(), nullable=False),
        sa.Column("evidence_id_bytes32", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("blockchain_network", sa.String(), nullable=True),
        sa.Column("contract_address", sa.String(), nullable=True),
        sa.Column("anchor_tx_hash", sa.String(), nullable=True),
        sa.Column("anchor_block_number", sa.Integer(), nullable=True),
        sa.Column("anchor_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("anchor_status", sa.String(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("evidence_id"),
        sa.UniqueConstraint("package_hash"),
    )
    op.create_index(
        "ix_merkle_package_root", "evidence_merkle_packages", ["merkle_root"]
    )

    # ------------------------------------------------------------------ #
    # evidence_merkle_leaves                                               #
    # ------------------------------------------------------------------ #
    op.create_table(
        "evidence_merkle_leaves",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("evidence_id", sa.String(), nullable=False),
        sa.Column("item_name", sa.String(), nullable=False),
        sa.Column("item_sha256", sa.String(), nullable=False),
        sa.Column("leaf_hash", sa.String(), nullable=False),
        sa.Column("proof_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence_merkle_packages.evidence_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_merkle_leaf_evidence",
        "evidence_merkle_leaves",
        ["evidence_id", "item_name"],
    )

    # ------------------------------------------------------------------ #
    # anchor_queue_entries                                                 #
    # ------------------------------------------------------------------ #
    op.create_table(
        "anchor_queue_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("evidence_id", sa.String(), nullable=False),
        sa.Column("root_hash", sa.String(), nullable=False),
        sa.Column("evidence_id_bytes32", sa.String(), nullable=False),
        sa.Column("blockchain_network", sa.String(), nullable=True),
        sa.Column("contract_address", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("tx_hash", sa.String(), nullable=True),
        sa.Column("block_number", sa.Integer(), nullable=True),
        sa.Column("anchor_timestamp", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence_merkle_packages.evidence_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_anchor_queue_status", "anchor_queue_entries", ["status"])
    op.create_index(
        "ix_anchor_queue_root", "anchor_queue_entries", ["root_hash"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_anchor_queue_root", table_name="anchor_queue_entries")
    op.drop_index("ix_anchor_queue_status", table_name="anchor_queue_entries")
    op.drop_table("anchor_queue_entries")
    op.drop_index("ix_merkle_leaf_evidence", table_name="evidence_merkle_leaves")
    op.drop_table("evidence_merkle_leaves")
    op.drop_index("ix_merkle_package_root", table_name="evidence_merkle_packages")
    op.drop_table("evidence_merkle_packages")
