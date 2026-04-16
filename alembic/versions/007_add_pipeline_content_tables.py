"""Add pipeline content tables: canonical_content_items and resolved_signals.

Revision ID: 007
Revises: 006
Create Date: 2026-04-16

These tables are the source layer read by the aggregation job
(aggregate_daily_market_metrics). They must exist in Railway Postgres
for server-side ingestion and re-aggregation to work.

canonical_content_items — normalized YouTube/Reddit/TikTok content records
resolved_signals        — entity resolution output per content item
"""

import sqlalchemy as sa
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_content_items",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("schema_version", sa.Text, nullable=False),
        sa.Column("source_platform", sa.Text, nullable=False),
        sa.Column("source_account_id", sa.Text, nullable=True),
        sa.Column("source_account_handle", sa.Text, nullable=True),
        sa.Column("source_account_type", sa.Text, nullable=True),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("external_content_id", sa.Text, nullable=True),
        sa.Column("published_at", sa.Text, nullable=False),
        sa.Column("collected_at", sa.Text, nullable=False),
        sa.Column("content_type", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("caption", sa.Text, nullable=True),
        sa.Column("text_content", sa.Text, nullable=True),
        sa.Column("hashtags_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("mentions_raw_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("media_metadata_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("engagement_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("language", sa.Text, nullable=True),
        sa.Column("region", sa.Text, nullable=False, server_default="US"),
        sa.Column("raw_payload_ref", sa.Text, nullable=False, server_default=""),
        sa.Column("normalizer_version", sa.Text, nullable=False, server_default="1.0"),
        sa.Column("query", sa.Text, nullable=True),
    )
    op.create_index(
        "ix_cci_source_platform", "canonical_content_items", ["source_platform"]
    )
    op.create_index(
        "ix_cci_published_at", "canonical_content_items", ["published_at"]
    )
    op.create_index(
        "ix_cci_external_content_id", "canonical_content_items", ["external_content_id"]
    )

    op.create_table(
        "resolved_signals",
        sa.Column(
            "id", sa.Integer, primary_key=True, autoincrement=True
        ),
        sa.Column("content_item_id", sa.Text, nullable=False),
        sa.Column("resolver_version", sa.Text, nullable=False, server_default="1.0"),
        sa.Column("resolved_entities_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("unresolved_mentions_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("alias_candidates_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.Text,
            nullable=False,
            server_default=sa.text("to_char(now(), 'YYYY-MM-DD HH24:MI:SS')"),
        ),
    )
    op.create_index(
        "uq_rs_content_item_id", "resolved_signals", ["content_item_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_rs_content_item_id", table_name="resolved_signals")
    op.drop_table("resolved_signals")
    op.drop_index("ix_cci_external_content_id", table_name="canonical_content_items")
    op.drop_index("ix_cci_published_at", table_name="canonical_content_items")
    op.drop_index("ix_cci_source_platform", table_name="canonical_content_items")
    op.drop_table("canonical_content_items")
