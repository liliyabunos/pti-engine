"""023 — YouTube Channel Registry + ingestion_method column

Adds:
  youtube_channels     — editorial registry of tracked YouTube channels
  canonical_content_items.ingestion_method — 'search' | 'channel_poll'

Revision ID: 023
Revises: 022
"""

from alembic import op
import sqlalchemy as sa

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "youtube_channels",
        sa.Column("id", sa.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("channel_id", sa.String(64), nullable=False, unique=True),
        sa.Column("handle", sa.String(255), nullable=True, unique=True),
        sa.Column("channel_url", sa.String(512), nullable=True),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("normalized_title", sa.String(512), nullable=True),
        sa.Column("quality_tier", sa.String(32), nullable=False, server_default="unrated"),
        sa.Column("category", sa.String(64), nullable=False, server_default="unknown"),
        sa.Column("country", sa.String(8), nullable=True),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("subscriber_count", sa.Integer(), nullable=True),
        sa.Column("video_count", sa.Integer(), nullable=True),
        sa.Column("view_count", sa.BigInteger(), nullable=True),
        sa.Column("channel_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("priority", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("uploads_playlist_id", sa.String(64), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_video_count", sa.Integer(), nullable=True),
        sa.Column("consecutive_empty_polls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_poll_status", sa.String(20), nullable=True),
        sa.Column("last_poll_error", sa.Text(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("added_by", sa.String(128), nullable=False, server_default="manual"),
        sa.Column("notes", sa.Text(), nullable=True),
    )

    op.create_index(
        "ix_youtube_channels_status_priority",
        "youtube_channels",
        ["status", "priority"],
    )
    op.create_index(
        "ix_youtube_channels_last_polled_at",
        "youtube_channels",
        ["last_polled_at"],
        postgresql_using="btree",
        postgresql_where=sa.text("last_polled_at IS NULL"),
    )

    # Add ingestion_method to canonical_content_items
    op.add_column(
        "canonical_content_items",
        sa.Column("ingestion_method", sa.String(32), nullable=True, server_default="search"),
    )


def downgrade() -> None:
    op.drop_column("canonical_content_items", "ingestion_method")
    op.drop_index("ix_youtube_channels_last_polled_at", table_name="youtube_channels")
    op.drop_index("ix_youtube_channels_status_priority", table_name="youtube_channels")
    op.drop_table("youtube_channels")
