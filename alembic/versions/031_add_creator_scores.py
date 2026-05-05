"""Add creator_scores table (C1.4)

Revision ID: 031
Revises: 030
Create Date: 2026-05-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "creator_scores",
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("creator_handle", sa.String(128), nullable=True),
        sa.Column("quality_tier", sa.String(32), nullable=True),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("subscriber_count", sa.Integer(), nullable=True),
        sa.Column("total_content_items", sa.Integer(), server_default="0", nullable=False),
        sa.Column("content_with_entity_mentions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("noise_rate", sa.Float(), nullable=True),
        sa.Column("unique_entities_mentioned", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unique_brands_mentioned", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_entity_mentions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_views", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("avg_views", sa.Float(), nullable=True),
        sa.Column("total_likes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("total_comments", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("avg_engagement_rate", sa.Float(), nullable=True),
        sa.Column("breakout_contributions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("early_signal_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("early_signal_rate", sa.Float(), nullable=True),
        sa.Column("influence_score", sa.Float(), nullable=True),
        sa.Column("score_components", JSONB(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=True),
        sa.PrimaryKeyConstraint("platform", "creator_id"),
    )
    op.create_index("idx_creator_scores_influence", "creator_scores", ["influence_score"])
    op.create_index("idx_creator_scores_early_signal", "creator_scores", ["early_signal_count"])


def downgrade() -> None:
    op.drop_index("idx_creator_scores_early_signal", table_name="creator_scores")
    op.drop_index("idx_creator_scores_influence", table_name="creator_scores")
    op.drop_table("creator_scores")
