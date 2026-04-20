"""Add Fragrantica enrichment tables.

Revision ID: 008
Revises: 007
Create Date: 2026-04-20

Adds five tables for the Fragrantica enrichment layer (Phase 1):

  fragrantica_records  — one row per successfully fetched + parsed Fragrantica page
  notes                — canonical note library (bergamot, rose, sandalwood, …)
  accords              — canonical accord library (floral, woody, fresh, …)
  perfume_notes        — many-to-many: perfume ↔ note with position (top/middle/base)
  perfume_accords      — many-to-many: perfume ↔ accord

All UUID PKs / FKs are stored as Text (36 chars) for SQLite + Postgres compatibility.
The fragrantica_records.fragrance_id is a reference key from the resolver DB
(fragrance_master.fragrance_id) — stored as TEXT, not a FK, since the resolver DB
lives in a separate file/schema.
"""

import sqlalchemy as sa
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # fragrantica_records
    # ------------------------------------------------------------------
    op.create_table(
        "fragrantica_records",
        sa.Column("id", sa.Text, primary_key=True),
        # fragrance_id from resolver fragrance_master (NOT a FK — cross-DB reference)
        sa.Column("fragrance_id", sa.Text, nullable=False),
        # market UUID from perfumes.id — may be NULL if identity map lookup failed
        sa.Column("perfume_id", sa.Text, nullable=True),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("raw_payload_ref", sa.Text, nullable=True),
        sa.Column("brand_name", sa.Text, nullable=True),
        sa.Column("perfume_name", sa.Text, nullable=True),
        sa.Column("accords_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("notes_top_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("notes_middle_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("notes_base_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("rating_value", sa.Float, nullable=True),
        sa.Column("rating_count", sa.Integer, nullable=True),
        sa.Column("release_year", sa.Integer, nullable=True),
        sa.Column("perfumer", sa.Text, nullable=True),
        sa.Column("gender", sa.Text, nullable=True),
        sa.Column("similar_perfumes_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("fetched_at", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index(
        "uq_fragrantica_records_fragrance_id",
        "fragrantica_records",
        ["fragrance_id"],
        unique=True,
    )
    op.create_index(
        "ix_fragrantica_records_perfume_id",
        "fragrantica_records",
        ["perfume_id"],
    )

    # ------------------------------------------------------------------
    # notes
    # ------------------------------------------------------------------
    op.create_table(
        "notes",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("normalized_name", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index("uq_notes_normalized_name", "notes", ["normalized_name"], unique=True)

    # ------------------------------------------------------------------
    # accords
    # ------------------------------------------------------------------
    op.create_table(
        "accords",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("normalized_name", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index("uq_accords_normalized_name", "accords", ["normalized_name"], unique=True)

    # ------------------------------------------------------------------
    # perfume_notes  (many-to-many: perfume ↔ note with position)
    # ------------------------------------------------------------------
    op.create_table(
        "perfume_notes",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("perfume_id", sa.Text, nullable=False),   # FK → perfumes.id (Text UUID)
        sa.Column("note_id", sa.Text, nullable=False),       # FK → notes.id (Text UUID)
        sa.Column("note_position", sa.Text, nullable=False, server_default="unknown"),
        sa.Column("source", sa.Text, nullable=False, server_default="fragrantica"),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index(
        "uq_perfume_notes_triplet",
        "perfume_notes",
        ["perfume_id", "note_id", "note_position"],
        unique=True,
    )
    op.create_index("ix_perfume_notes_perfume_id", "perfume_notes", ["perfume_id"])
    op.create_index("ix_perfume_notes_note_id", "perfume_notes", ["note_id"])

    # ------------------------------------------------------------------
    # perfume_accords  (many-to-many: perfume ↔ accord)
    # ------------------------------------------------------------------
    op.create_table(
        "perfume_accords",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("perfume_id", sa.Text, nullable=False),   # FK → perfumes.id (Text UUID)
        sa.Column("accord_id", sa.Text, nullable=False),    # FK → accords.id (Text UUID)
        sa.Column("source", sa.Text, nullable=False, server_default="fragrantica"),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index(
        "uq_perfume_accords_pair",
        "perfume_accords",
        ["perfume_id", "accord_id"],
        unique=True,
    )
    op.create_index("ix_perfume_accords_perfume_id", "perfume_accords", ["perfume_id"])
    op.create_index("ix_perfume_accords_accord_id", "perfume_accords", ["accord_id"])


def downgrade() -> None:
    op.drop_index("ix_perfume_accords_accord_id", table_name="perfume_accords")
    op.drop_index("ix_perfume_accords_perfume_id", table_name="perfume_accords")
    op.drop_index("uq_perfume_accords_pair", table_name="perfume_accords")
    op.drop_table("perfume_accords")

    op.drop_index("ix_perfume_notes_note_id", table_name="perfume_notes")
    op.drop_index("ix_perfume_notes_perfume_id", table_name="perfume_notes")
    op.drop_index("uq_perfume_notes_triplet", table_name="perfume_notes")
    op.drop_table("perfume_notes")

    op.drop_index("uq_accords_normalized_name", table_name="accords")
    op.drop_table("accords")

    op.drop_index("uq_notes_normalized_name", table_name="notes")
    op.drop_table("notes")

    op.drop_index("ix_fragrantica_records_perfume_id", table_name="fragrantica_records")
    op.drop_index("uq_fragrantica_records_fragrance_id", table_name="fragrantica_records")
    op.drop_table("fragrantica_records")
