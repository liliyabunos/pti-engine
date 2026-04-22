"""Add resolver_perfume_notes and resolver_perfume_accords tables (Phase 1B — Bulk Notes Backfill).

Revision ID: 017
Revises: 016
Create Date: 2026-04-22

Adds two resolver-linked notes tables:

  resolver_perfume_notes   — notes (top/middle/base) keyed by resolver_perfumes.id (integer)
  resolver_perfume_accords — accords keyed by resolver_perfumes.id (integer)

These tables hold dataset-imported notes (Parfumo / Kaggle) for the full 56k catalog.
They are keyed by resolver integer IDs, NOT by entity_market UUIDs, so they cover
all known catalog perfumes regardless of ingestion activity.

The entity API reads fragrantica_records first (scraped, higher quality), then falls
back to these tables when no fragrantica record exists.
"""

import sqlalchemy as sa
from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # resolver_perfume_notes
    # ------------------------------------------------------------------
    op.create_table(
        "resolver_perfume_notes",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        # FK to resolver_perfumes.id (integer) — cross-table but same DB in Postgres
        sa.Column("resolver_perfume_id", sa.Integer(), nullable=False),
        sa.Column("note_name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        # top | middle | base
        sa.Column("position", sa.Text(), nullable=False),
        # parfumo_v1 | kaggle_v1 | manual
        sa.Column("source", sa.Text(), nullable=False, server_default="'parfumo_v1'"),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_rpn_resolver_perfume_id",
        "resolver_perfume_notes",
        ["resolver_perfume_id"],
    )
    op.create_index(
        "uq_rpn_perfume_note_position",
        "resolver_perfume_notes",
        ["resolver_perfume_id", "normalized_name", "position"],
        unique=True,
    )
    op.create_index(
        "ix_rpn_normalized_name",
        "resolver_perfume_notes",
        ["normalized_name"],
    )

    # ------------------------------------------------------------------
    # resolver_perfume_accords
    # ------------------------------------------------------------------
    op.create_table(
        "resolver_perfume_accords",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("resolver_perfume_id", sa.Integer(), nullable=False),
        sa.Column("accord_name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False, server_default="'parfumo_v1'"),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_rpa_resolver_perfume_id",
        "resolver_perfume_accords",
        ["resolver_perfume_id"],
    )
    op.create_index(
        "uq_rpa_perfume_accord",
        "resolver_perfume_accords",
        ["resolver_perfume_id", "normalized_name"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("resolver_perfume_accords")
    op.drop_table("resolver_perfume_notes")
