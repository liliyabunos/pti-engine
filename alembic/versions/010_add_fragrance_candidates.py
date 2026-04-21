"""Add fragrance_candidates table (Phase 3 — Discovery Layer).

Revision ID: 010
Revises: 009
Create Date: 2026-04-21

Stores unresolved perfume/brand mentions from ingestion pipelines.
Each unique normalized_text is a candidate for future promotion into
fragrance_master after validation.

Idempotency: upsert on normalized_text (unique constraint).
"""

from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fragrance_candidates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("source_platform", sa.Text(), nullable=True),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("occurrences", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen", sa.Text(), nullable=False),
        sa.Column("last_seen", sa.Text(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("status", sa.Text(), nullable=False, server_default="new"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_text", name="uq_fragrance_candidates_normalized_text"),
    )
    op.create_index("ix_fragrance_candidates_status", "fragrance_candidates", ["status"])
    op.create_index("ix_fragrance_candidates_occurrences", "fragrance_candidates", ["occurrences"])
    op.create_index("ix_fragrance_candidates_source_platform", "fragrance_candidates", ["source_platform"])


def downgrade() -> None:
    op.drop_table("fragrance_candidates")
