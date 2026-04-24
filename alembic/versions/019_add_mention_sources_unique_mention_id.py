"""Add unique constraint on mention_sources.mention_id (Phase I1 fix).

Revision ID: 019
Revises: 018
Create Date: 2026-04-24

Deduplicates existing mention_sources rows and adds UNIQUE constraint on mention_id
so ON CONFLICT (mention_id) DO NOTHING works correctly in backfill and live pipeline.
"""

from alembic import op
import sqlalchemy as sa


revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Remove duplicate mention_sources rows (keep one per mention_id, lowest created_at)
    op.execute("""
        DELETE FROM mention_sources
        WHERE id NOT IN (
            SELECT DISTINCT ON (mention_id) id
            FROM mention_sources
            ORDER BY mention_id, created_at ASC
        )
    """)

    # Add unique constraint
    op.create_unique_constraint(
        "uq_mention_sources_mention_id",
        "mention_sources",
        ["mention_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_mention_sources_mention_id", "mention_sources", type_="unique")
