"""SC1.1 TikTok Layer 1 — add layer/weight columns to canonical_content_items.

Revision ID: 034
Revises: 033
Create Date: 2026-05-07

SC1.1 adds three metadata columns that distinguish how a TikTok content item
entered the pipeline, and one weight column that controls aggregation:

  tiktok_layer            INTEGER  NULL
    1 = URL/embed/mention (Layer 1 — directly from a TikTok video URL)
    NULL = non-TikTok item (YouTube, Reddit) or legacy TikTok row
    3 = seeded watchlist (Layer 3, planned in SC1.3 — reserved, not yet used)

  referencing_source_id   TEXT     NULL
    For derived items (mention_weight_override = 0.0): the id of the parent
    canonical_content_item (YouTube/Reddit) whose text_content contained this
    TikTok URL. NULL for directly ingested items.

  referencing_context     TEXT     NULL
    Short snippet (≤ 200 chars) from the parent item's text_content where the
    TikTok URL appeared. Used for audit/resolver context only. NULL for direct.

  mention_weight_override FLOAT    NULL
    Override applied in the aggregator INSTEAD of the platform default weight.
    NULL   = use platform default weight (_PLATFORM_WEIGHTS["tiktok"] = 0.9)
    0.0    = derived item (URL extracted from YouTube/Reddit text) — does NOT
             contribute a mention; stored for resolver enrichment only
    0.7    = direct submission via submit-source with context provided

The public_safe_content_items view is updated to include TikTok rows ONLY when:
  tiktok_layer = 1 AND mention_weight_override > 0.0
This prevents derived/enrichment-only TikTok records from appearing in the
public API while still exposing genuine TikTok signal items.
"""

from alembic import op
import sqlalchemy as sa

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


_PUBLIC_SAFE_CONTENT_ITEMS_V2 = """
CREATE OR REPLACE VIEW public_safe_content_items AS
SELECT
    cci.id,
    cci.source_platform,
    cci.source_url,
    cci.title,
    cci.content_type,
    cci.published_at,
    cci.ingestion_method,
    cci.engagement_json
FROM canonical_content_items cci
WHERE
    cci.source_platform IN ('youtube', 'reddit')
    OR (
        cci.source_platform = 'tiktok'
        AND cci.tiktok_layer = 1
        AND cci.mention_weight_override > 0.0
    )
;
"""


def upgrade() -> None:
    op.add_column(
        "canonical_content_items",
        sa.Column("tiktok_layer", sa.Integer, nullable=True),
    )
    op.add_column(
        "canonical_content_items",
        sa.Column("referencing_source_id", sa.Text, nullable=True),
    )
    op.add_column(
        "canonical_content_items",
        sa.Column("referencing_context", sa.Text, nullable=True),
    )
    op.add_column(
        "canonical_content_items",
        sa.Column("mention_weight_override", sa.Float, nullable=True),
    )

    # Update the compliance view to include qualified TikTok rows.
    # PostgreSQL only — SQLite local dev skips.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(_PUBLIC_SAFE_CONTENT_ITEMS_V2)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Revert to migration-032 view definition (YouTube + Reddit only)
        op.execute("""
            CREATE OR REPLACE VIEW public_safe_content_items AS
            SELECT
                cci.id,
                cci.source_platform,
                cci.source_url,
                cci.title,
                cci.content_type,
                cci.published_at,
                cci.ingestion_method,
                cci.engagement_json
            FROM canonical_content_items cci
            WHERE cci.source_platform IN ('youtube', 'reddit')
            ;
        """)

    op.drop_column("canonical_content_items", "mention_weight_override")
    op.drop_column("canonical_content_items", "referencing_context")
    op.drop_column("canonical_content_items", "referencing_source_id")
    op.drop_column("canonical_content_items", "tiktok_layer")
