"""Add public_safe_* database views (Compliance Boundary v1).

Revision ID: 032
Revises: 031
Create Date: 2026-05-06

These views enforce the public export policy defined in
config/public_export_policy.yaml. They contain ONLY the fields that are
permitted in customer-facing API responses and analytical exports.

Views created:
  public_safe_entity_snapshots  — entity identity + latest aggregated metrics
  public_safe_signals           — breakout/acceleration signals (clean)
  public_safe_content_items     — content items WITHOUT raw text/body/handles

Fields deliberately EXCLUDED from all views:
  text_content, caption, raw_text, raw_payload_ref, mentions_raw_json,
  hashtags_json, media_metadata_json, source_account_id,
  source_account_handle, external_content_id, author_id, author_name

Note: entity_market has no state/trend_state columns — trend_state is
sourced from the entity_timeseries_daily LATERAL join.

These views are PostgreSQL-only. SQLite (local dev) silently skips creation.
"""

from alembic import op

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# View SQL
# ---------------------------------------------------------------------------

_PUBLIC_SAFE_ENTITY_SNAPSHOTS = """
CREATE OR REPLACE VIEW public_safe_entity_snapshots AS
SELECT
    em.entity_id,
    em.entity_type,
    em.canonical_name,
    em.brand_name,
    em.ticker,
    -- Latest snapshot metrics (aggregated — no individual attribution)
    ts.date,
    ts.trend_state,
    ts.mention_count,
    ts.unique_authors,               -- count only, no list
    ts.engagement_sum,
    ts.composite_market_score        AS trend_score,
    ts.weighted_signal_score,
    ts.confidence_avg,
    ts.momentum,
    ts.acceleration,
    ts.volatility,
    ts.growth_rate
FROM entity_market em
LEFT JOIN LATERAL (
    SELECT *
    FROM entity_timeseries_daily etd
    WHERE etd.entity_id = em.id
    ORDER BY etd.date DESC
    LIMIT 1
) ts ON TRUE
;
"""

_PUBLIC_SAFE_SIGNALS = """
CREATE OR REPLACE VIEW public_safe_signals AS
SELECT
    -- Entity reference (no raw attribution)
    CAST(s.entity_id AS TEXT)        AS entity_id,
    em.entity_type,
    em.canonical_name,
    em.brand_name,
    -- Signal data
    s.signal_type,
    s.detected_at                    AS signal_date,
    s.strength                       AS signal_strength,
    s.confidence                     AS signal_confidence
FROM signals s
JOIN entity_market em ON em.id = s.entity_id
;
"""

_PUBLIC_SAFE_CONTENT_ITEMS = """
CREATE OR REPLACE VIEW public_safe_content_items AS
SELECT
    -- Internal reference only (not for user display)
    cci.id,
    cci.source_platform,
    cci.source_url,               -- public URL to the content
    cci.title,                    -- public title of the video/post
    cci.content_type,
    cci.published_at,
    cci.ingestion_method,
    -- Engagement (aggregated metrics, not raw responses)
    cci.engagement_json
    -- EXPLICITLY EXCLUDED:
    -- cci.text_content         (raw body text — NLP/extraction only)
    -- cci.caption              (raw caption text — NLP/extraction only)
    -- cci.source_account_id    (internal platform UID)
    -- cci.source_account_handle (raw ingestion handle)
    -- cci.source_account_type  (internal classification)
    -- cci.external_content_id  (platform-internal ID)
    -- cci.mentions_raw_json    (raw platform mention payload)
    -- cci.hashtags_json        (raw hashtag payload)
    -- cci.media_metadata_json  (internal processing metadata)
    -- cci.raw_payload_ref      (internal ingestion artifact)
    -- cci.normalizer_version   (internal versioning)
    -- cci.schema_version       (internal versioning)
FROM canonical_content_items cci
WHERE cci.source_platform IN ('youtube', 'reddit')
;
"""

_DROP_PUBLIC_SAFE_ENTITY_SNAPSHOTS = "DROP VIEW IF EXISTS public_safe_entity_snapshots;"
_DROP_PUBLIC_SAFE_SIGNALS = "DROP VIEW IF EXISTS public_safe_signals;"
_DROP_PUBLIC_SAFE_CONTENT_ITEMS = "DROP VIEW IF EXISTS public_safe_content_items;"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite local dev — views use LATERAL which is PostgreSQL-specific.
        # Skip silently; compliance views are a production concern.
        return

    op.execute(_PUBLIC_SAFE_ENTITY_SNAPSHOTS)
    op.execute(_PUBLIC_SAFE_SIGNALS)
    op.execute(_PUBLIC_SAFE_CONTENT_ITEMS)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(_DROP_PUBLIC_SAFE_CONTENT_ITEMS)
    op.execute(_DROP_PUBLIC_SAFE_SIGNALS)
    op.execute(_DROP_PUBLIC_SAFE_ENTITY_SNAPSHOTS)
