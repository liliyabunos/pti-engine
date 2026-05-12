"""DATA0 — Historical Metric Provenance & Topic Distribution History

Revision ID: 043
Revises: 042
Create Date: 2026-05-12

Three workstreams:

1. entity_timeseries_daily.score_formula_version (INTEGER, NOT NULL, DEFAULT 1)
   Every daily market score row now carries the version of the formula that
   produced it. When the aggregation formula changes, the version is bumped,
   making historical rows comparable and citable in future reports.
   Existing rows receive baseline version 1 via server_default.

2. signals.signal_threshold_version (INTEGER, NOT NULL, DEFAULT 1)
   Every signal row carries the version of the breakout-detection threshold
   set that produced it. Future threshold tuning bumps this version so
   historical signals remain independently citable with methodology footnotes.
   Existing rows receive baseline version 1 via server_default.

3. entity_topic_snapshots table
   After each --rebuild-links run, a dated aggregate snapshot of
   entity_topic_links is persisted here. This preserves the ability to
   query historical topic/intent distributions over time, even though
   entity_topic_links is rebuilt (wiped and reconstructed) on every cycle.

   Unique on (snapshot_date, entity_id, topic_type, topic_text) — idempotent
   re-runs on the same date overwrite without duplicating.

Design decision: Option A (new snapshot table) over Option B (append-with-date
to entity_topic_links) because entity_topic_links is consumed by existing API
queries that aggregate over all rows for an entity. Adding a date dimension to
those rows would distort current-state aggregation and require significant query
rewrites. The snapshot table is purely additive — zero impact on existing paths.

Provenance note: existing historical rows in entity_timeseries_daily and signals
predate explicit version tracking but are assigned version=1 (the baseline) for
continuity. This is documented in docs/ops/DATA_RETENTION_POLICY.md.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Score formula version on entity_timeseries_daily ─────────────────
    # server_default="1" causes Postgres to backfill all existing rows instantly.
    op.add_column(
        "entity_timeseries_daily",
        sa.Column(
            "score_formula_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="Version of the composite_market_score formula. Bump when formula changes.",
        ),
    )

    # ── 2. Signal threshold version on signals ───────────────────────────────
    op.add_column(
        "signals",
        sa.Column(
            "signal_threshold_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="Version of the breakout detection threshold set. Bump when thresholds change.",
        ),
    )

    # ── 3. entity_topic_snapshots ────────────────────────────────────────────
    # Dated aggregate of entity_topic_links, written after each --rebuild-links run.
    # Preserves historical topic/intent distribution across pipeline cycles.
    op.create_table(
        "entity_topic_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        # Identity
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),       # matches entity_topic_links.entity_id (UUID string)
        sa.Column("entity_type", sa.String(32), nullable=False),
        # Topic
        sa.Column("topic_type", sa.String(32), nullable=False),  # 'topic' | 'query' | 'subreddit'
        sa.Column("topic_text", sa.Text(), nullable=False),
        # Aggregated metrics from entity_topic_links at snapshot time
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("avg_source_score", sa.Float(), nullable=True),
        # Provenance
        sa.Column(
            "formula_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="Topic distribution formula version. Bump if topic extraction logic changes.",
        ),
        sa.Column(
            "generated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # Primary access path: by entity + date range for trend analysis
    op.create_index(
        "ix_entity_topic_snapshots_entity_date",
        "entity_topic_snapshots",
        ["entity_id", "snapshot_date"],
    )

    # Date-first index for platform-wide "what was trending on date X" queries
    op.create_index(
        "ix_entity_topic_snapshots_date",
        "entity_topic_snapshots",
        ["snapshot_date"],
    )

    # Unique: one aggregated row per (date, entity, topic_type, topic_text)
    # Enables idempotent ON CONFLICT DO UPDATE re-runs
    op.create_unique_constraint(
        "uq_entity_topic_snapshots_key",
        "entity_topic_snapshots",
        ["snapshot_date", "entity_id", "topic_type", "topic_text"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_entity_topic_snapshots_key", "entity_topic_snapshots", type_="unique")
    op.drop_index("ix_entity_topic_snapshots_date", table_name="entity_topic_snapshots")
    op.drop_index("ix_entity_topic_snapshots_entity_date", table_name="entity_topic_snapshots")
    op.drop_table("entity_topic_snapshots")

    op.drop_column("signals", "signal_threshold_version")
    op.drop_column("entity_timeseries_daily", "score_formula_version")
