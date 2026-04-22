"""Add maintenance queue tables (Phase 5 — Coverage Maintenance Service).

Revision ID: 016
Revises: 015
Create Date: 2026-04-22

Adds two queue tables:

  stale_entity_queue   — entities with no recent market activity, detected for refresh
  metadata_gap_queue   — entities with missing metadata (notes, accords, etc.)

Both tables are idempotent-insert-safe via unique constraints defined inline
(SQLite-compatible — no separate ALTER TABLE ADD CONSTRAINT).
"""

import sqlalchemy as sa
from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # stale_entity_queue
    # ------------------------------------------------------------------
    op.create_table(
        "stale_entity_queue",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        # entity_market.id (UUID as Text) — one row per entity
        sa.Column("entity_id", sa.Text(), nullable=False, unique=True),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="5"),
        # pending / processing / detected_only / done / failed
        sa.Column("status", sa.Text(), nullable=False, server_default="'pending'"),
        sa.Column("last_seen_date", sa.Text(), nullable=True),
        sa.Column("days_inactive", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("last_attempted_at", sa.Text(), nullable=True),
        sa.Column("notes_json", sa.Text(), nullable=True, server_default="'{}'"),
    )
    op.create_index("ix_stale_entity_queue_entity_id", "stale_entity_queue", ["entity_id"])
    op.create_index("ix_stale_entity_queue_status", "stale_entity_queue", ["status"])

    # ------------------------------------------------------------------
    # metadata_gap_queue
    # ------------------------------------------------------------------
    op.create_table(
        "metadata_gap_queue",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        # entity_market.id (UUID as Text)
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=True),
        # gap type: missing_notes | missing_accords | missing_fragrantica | missing_brand_info
        sa.Column("gap_type", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="5"),
        # pending / processing / pending_enrichment / done / failed
        sa.Column("status", sa.Text(), nullable=False, server_default="'pending'"),
        # resolver fragrance_id if known (for enrichment path lookup)
        sa.Column("fragrance_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("last_attempted_at", sa.Text(), nullable=True),
        sa.Column("notes_json", sa.Text(), nullable=True, server_default="'{}'"),
        # One entry per (entity, gap_type) — prevents re-detecting the same gap
        sa.UniqueConstraint("entity_id", "gap_type", name="uq_metadata_gap_queue_entity_gap"),
    )
    op.create_index("ix_metadata_gap_queue_entity_id", "metadata_gap_queue", ["entity_id"])
    op.create_index("ix_metadata_gap_queue_gap_type", "metadata_gap_queue", ["gap_type"])
    op.create_index("ix_metadata_gap_queue_status", "metadata_gap_queue", ["status"])


def downgrade() -> None:
    op.drop_table("metadata_gap_queue")
    op.drop_table("stale_entity_queue")
