"""022 — Phase I5: Topic/Query Intelligence tables

Adds:
  content_topics       — topics extracted deterministically from content items
  entity_topic_links   — M2M between entities and topics (via content)

Revision ID: 022
Revises: 021
"""

from alembic import op
import sqlalchemy as sa

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── content_topics ──────────────────────────────────────────────────────
    # One row per (content_item, topic_type, topic_text).
    # content_item_id references canonical_content_items.id (text PK).
    op.create_table(
        "content_topics",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("content_item_id", sa.Text, nullable=False, index=True),
        sa.Column("source_platform", sa.String(64), nullable=True),
        # topic_type: 'query' | 'topic' | 'keyword' | 'subreddit'
        sa.Column("topic_type", sa.String(32), nullable=False, index=True),
        sa.Column("topic_text", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("content_item_id", "topic_type", "topic_text", name="uq_content_topics_item_type_text"),
    )
    op.create_index("ix_content_topics_type_text", "content_topics", ["topic_type", "topic_text"])

    # ── entity_topic_links ──────────────────────────────────────────────────
    # Links entity_market entities to content topics via their content mention.
    op.create_table(
        "entity_topic_links",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        # Entity reference (entity_market.id — UUID stored as text for SQLite compat)
        sa.Column("entity_id", sa.Text, nullable=False, index=True),
        sa.Column("entity_type", sa.String(32), nullable=False),
        # Topic reference (denormalized for query efficiency)
        sa.Column("content_topic_id", sa.Integer, sa.ForeignKey("content_topics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic_text", sa.Text, nullable=False),
        sa.Column("topic_type", sa.String(32), nullable=False),
        # Source quality score from mention_sources (nullable — not all mentions are scored)
        sa.Column("source_score", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("entity_id", "content_topic_id", name="uq_entity_topic_links_entity_topic"),
    )
    op.create_index("ix_entity_topic_links_entity_type", "entity_topic_links", ["entity_id", "topic_type"])
    op.create_index("ix_entity_topic_links_topic_type_text", "entity_topic_links", ["topic_type", "topic_text"])


def downgrade() -> None:
    op.drop_table("entity_topic_links")
    op.drop_table("content_topics")
