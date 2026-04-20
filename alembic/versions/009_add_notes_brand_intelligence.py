"""Add Notes & Brand Intelligence tables (Phase 2).

Revision ID: 009
Revises: 008
Create Date: 2026-04-20

Adds five analytical tables on top of existing notes/accords data:

  notes_canonical     — semantic canonical note groups
  note_canonical_map  — maps notes.id → notes_canonical.id
  note_stats          — precomputed per-canonical-note statistics
  accord_stats        — precomputed per-accord statistics
  note_brand_stats    — note × brand relationship stats

All tables are populated by build_notes_intelligence.py — never by ingestion.
Safe to truncate + rebuild at any time.
"""

from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # notes_canonical
    op.create_table(
        "notes_canonical",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("note_family", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name", name="uq_notes_canonical_normalized"),
    )

    # note_canonical_map
    op.create_table(
        "note_canonical_map",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("note_id", sa.Text(), nullable=False),
        sa.Column("canonical_note_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("note_id", name="uq_note_canonical_map_note_id"),
    )
    op.create_index("ix_note_canonical_map_canonical_id", "note_canonical_map", ["canonical_note_id"])

    # note_stats
    op.create_table(
        "note_stats",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("canonical_note_id", sa.Text(), nullable=False),
        sa.Column("perfume_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("brand_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("top_position_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("middle_position_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("base_position_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unknown_position_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("computed_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_note_id", name="uq_note_stats_canonical"),
    )
    op.create_index("ix_note_stats_canonical_note_id", "note_stats", ["canonical_note_id"])

    # accord_stats
    op.create_table(
        "accord_stats",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("accord_id", sa.Text(), nullable=False),
        sa.Column("perfume_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("brand_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("computed_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("accord_id", name="uq_accord_stats_accord"),
    )
    op.create_index("ix_accord_stats_accord_id", "accord_stats", ["accord_id"])

    # note_brand_stats
    op.create_table(
        "note_brand_stats",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("canonical_note_id", sa.Text(), nullable=False),
        sa.Column("brand_id", sa.Text(), nullable=False),
        sa.Column("perfume_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("share", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("computed_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_note_id", "brand_id", name="uq_note_brand_stats_pair"),
    )
    op.create_index("ix_note_brand_stats_note", "note_brand_stats", ["canonical_note_id"])
    op.create_index("ix_note_brand_stats_brand", "note_brand_stats", ["brand_id"])


def downgrade() -> None:
    op.drop_table("note_brand_stats")
    op.drop_table("accord_stats")
    op.drop_table("note_stats")
    op.drop_table("note_canonical_map")
    op.drop_table("notes_canonical")
