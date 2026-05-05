"""Add creator_entity_relationships table (C1.3)

Revision ID: 030
Revises: 029
Create Date: 2026-05-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "creator_entity_relationships",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("creator_handle", sa.String(128), nullable=True),
        sa.Column("entity_id", UUID(as_uuid=False), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=True),
        sa.Column("canonical_name", sa.String(256), nullable=True),
        sa.Column("brand_name", sa.String(256), nullable=True),
        sa.Column("mention_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unique_content_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("first_mention_date", sa.Date(), nullable=True),
        sa.Column("last_mention_date", sa.Date(), nullable=True),
        sa.Column("total_views", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("avg_views", sa.Float(), nullable=True),
        sa.Column("total_likes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("total_comments", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("avg_engagement_rate", sa.Float(), nullable=True),
        sa.Column("mentions_before_first_breakout", sa.Integer(), server_default="0", nullable=False),
        sa.Column("days_before_first_breakout", sa.Integer(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "platform", "creator_id", "entity_id",
            name="uq_cer_platform_creator_entity",
        ),
    )
    op.create_index("idx_cer_creator", "creator_entity_relationships", ["platform", "creator_id"])
    op.create_index("idx_cer_entity", "creator_entity_relationships", ["entity_id"])
    op.create_index(
        "idx_cer_early_signal",
        "creator_entity_relationships",
        ["mentions_before_first_breakout"],
    )


def downgrade() -> None:
    op.drop_index("idx_cer_early_signal", table_name="creator_entity_relationships")
    op.drop_index("idx_cer_entity", table_name="creator_entity_relationships")
    op.drop_index("idx_cer_creator", table_name="creator_entity_relationships")
    op.drop_table("creator_entity_relationships")
