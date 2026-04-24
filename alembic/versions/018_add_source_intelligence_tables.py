"""Add source_profiles and mention_sources tables (Phase I1 — Source Intelligence).

Revision ID: 018
Revises: 017
Create Date: 2026-04-24

Additive migration — no existing tables modified.

  source_profiles  — channel / author profile data, one row per (platform, source_id)
  mention_sources  — raw engagement attached to each entity mention
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("platform", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("source_name", sa.String(512), nullable=True),
        sa.Column("subscribers", sa.Integer(), nullable=True),
        sa.Column("avg_views", sa.Integer(), nullable=True),
        sa.Column("total_videos", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.UniqueConstraint("platform", "source_id", name="uq_source_profiles_platform_source"),
    )
    op.create_index("ix_source_profiles_platform_source_id",
                    "source_profiles", ["platform", "source_id"])

    op.create_table(
        "mention_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("mention_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("source_name", sa.String(512), nullable=True),
        sa.Column("views", sa.Integer(), nullable=True),
        sa.Column("likes", sa.Integer(), nullable=True),
        sa.Column("comments_count", sa.Integer(), nullable=True),
        sa.Column("engagement_rate", sa.Float(), nullable=True),
        sa.Column("source_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
    )
    op.create_index("ix_mention_sources_mention_id",
                    "mention_sources", ["mention_id"])
    op.create_index("ix_mention_sources_platform_source_id",
                    "mention_sources", ["platform", "source_id"])


def downgrade() -> None:
    op.drop_table("mention_sources")
    op.drop_table("source_profiles")
