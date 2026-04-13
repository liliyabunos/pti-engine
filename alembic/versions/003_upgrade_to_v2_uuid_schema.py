"""Upgrade to v2 UUID schema (breaking migration)

Revision ID: 003
Revises: 002
Create Date: 2026-04-10

THIS IS A BREAKING MIGRATION. READ CAREFULLY BEFORE APPLYING.

== What changes ==

1. entity_market
   - ADD: UUID column `id` (gen_random_uuid(), becomes new primary key)
   - ADD: DateTime column `created_at`
   - KEEP: `entity_id` String (canonical name) becomes unique NOT NULL
   - BREAKING: primary key changes from String `entity_id` to UUID `id`

2. entity_daily_snapshots → (DROP + CREATE as entity_timeseries_daily)
   - REASON: Integer PK and String entity_id cannot be safely cast to UUID.
     No lossless migration path exists. Data in this table is DISCARDED.
   - NEW TABLE: entity_timeseries_daily with UUID PK, UUID entity_id,
     added columns: entity_type, confidence_avg, search_index, retailer_score,
     growth_rate, updated_at
   - REMOVED columns: trend_score, source_diversity, mentions_prev_day, growth
   - RENAMED column: (new) date is Date type (was String)

3. market_signals → (DROP + CREATE as signals)
   - REASON: same as above — Integer PK and String entity_id cannot be cast to UUID.
     Data in this table is DISCARDED.
   - NEW TABLE: signals with UUID PK, UUID entity_id, entity_type, strength
     (was score), confidence, trigger_value, baseline_value, metadata_json JSON
     (was details_json Text), detected_at DateTime(timezone=True) (was String)

4. brands → (DROP + CREATE)
   - REASON: Integer PK cannot be safely cast to UUID. Data is DISCARDED.
   - NEW TABLE: brands with UUID PK, name, slug, ticker, country, segment,
     price_tier, description, created_at DateTime

5. perfumes → (DROP + CREATE)
   - REASON: Integer PK and Integer brand_id FK cannot be safely cast to UUID.
     Data is DISCARDED.
   - NEW TABLE: perfumes with UUID PK, brand_id UUID FK, name, slug, ticker,
     launch_year, gender_position, olfactive_family, price_band, concentration,
     notes_summary, created_at DateTime

6. entity_mentions → (DROP + CREATE)
   - REASON: Integer PK and String entity_id cannot be safely cast to UUID.
     Data is DISCARDED.
   - NEW TABLE: entity_mentions with UUID PK, UUID entity_id, entity_type,
     source_type, source_platform, source_url, author_id, author_name,
     mention_count, influence_score, sentiment Float (was String), confidence,
     engagement, region, channel, occurred_at DateTime, metadata_json JSON,
     created_at DateTime

== Why this migration is irreversible ==

- String → UUID casts have no safe path for arbitrary canonical name strings.
- Table renames combined with type changes prevent column-level alter operations.
- The downgrade() function recreates the old v1 tables but CANNOT restore
  any data that was in them before this migration was applied.

== Required indexes (new schema) ==

- entity_mentions(entity_type, entity_id, occurred_at)      composite
- entity_timeseries_daily(entity_type, entity_id, date)     composite
- signals(entity_type, entity_id, signal_type, detected_at) composite

== RECOMMENDED BACKUP STEPS BEFORE APPLYING ==

  1. pg_dump -Fc your_database > backup_before_003_$(date +%Y%m%d).dump
  2. Verify backup is readable: pg_restore --list backup_before_003_*.dump
  3. Note that entity_daily_snapshots, market_signals, brands, perfumes,
     entity_mentions data will be PERMANENTLY LOST after this migration.
  4. Apply: alembic upgrade 003
  5. Re-run aggregation jobs to repopulate time-series and signal tables.

== PostgreSQL requirement ==

This migration uses gen_random_uuid() and PostgreSQL-native UUID type.
It is NOT compatible with SQLite. Test environments use SQLite via direct
schema creation through MarketStore.init_schema(), not Alembic.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid_col(name: str, **kwargs) -> sa.Column:
    """Shorthand for a UUID column."""
    return sa.Column(name, postgresql.UUID(as_uuid=True), **kwargs)


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. entity_market — add UUID PK, keep entity_id as unique String
    # ------------------------------------------------------------------
    # Add UUID id column, defaulting to gen_random_uuid() so existing rows
    # get a UUID immediately.
    op.add_column(
        "entity_market",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=True,
        ),
    )
    # Populate any rows that somehow have NULL (safety net).
    op.execute("UPDATE entity_market SET id = gen_random_uuid() WHERE id IS NULL")
    # Lock the column as NOT NULL before making it the PK.
    op.alter_column("entity_market", "id", nullable=False)

    # Drop the old primary key constraint (entity_id was the PK).
    op.drop_constraint("entity_market_pkey", "entity_market", type_="primary")

    # New primary key on UUID id.
    op.create_primary_key("entity_market_pkey", "entity_market", ["id"])

    # entity_id (canonical name string) becomes a unique indexed column.
    op.create_unique_constraint(
        "uq_entity_market_entity_id", "entity_market", ["entity_id"]
    )
    op.create_index("ix_entity_market_entity_id", "entity_market", ["entity_id"])

    # Add created_at; backfill with NOW() then make NOT NULL.
    op.add_column(
        "entity_market",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE entity_market SET created_at = NOW()")
    op.alter_column("entity_market", "created_at", nullable=False)

    # ------------------------------------------------------------------
    # 2. entity_daily_snapshots → entity_timeseries_daily
    #    DESTRUCTIVE: old data is discarded (Integer PK / String entity_id
    #    cannot be cast to UUID).
    # ------------------------------------------------------------------
    op.drop_index("ix_entity_daily_snapshots_entity_id", table_name="entity_daily_snapshots")
    op.drop_table("entity_daily_snapshots")

    op.create_table(
        "entity_timeseries_daily",
        _uuid_col("id", nullable=False, server_default=sa.text("gen_random_uuid()")),
        _uuid_col("entity_id", nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("mention_count", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unique_authors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("engagement_sum", sa.Float(), nullable=False, server_default="0"),
        sa.Column("sentiment_avg", sa.Float(), nullable=True),
        sa.Column("confidence_avg", sa.Float(), nullable=True),
        sa.Column("search_index", sa.Float(), nullable=True),
        sa.Column("retailer_score", sa.Float(), nullable=True),
        sa.Column("growth_rate", sa.Float(), nullable=True),
        sa.Column("composite_market_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("momentum", sa.Float(), nullable=True),
        sa.Column("acceleration", sa.Float(), nullable=True),
        sa.Column("volatility", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entity_id", "entity_type", "date",
            name="uq_entity_timeseries_daily",
        ),
    )
    op.create_index(
        "ix_entity_timeseries_daily_entity_id",
        "entity_timeseries_daily", ["entity_id"],
    )
    op.create_index(
        "ix_entity_timeseries_daily_entity_type",
        "entity_timeseries_daily", ["entity_type"],
    )
    op.create_index(
        "ix_entity_timeseries_daily_date",
        "entity_timeseries_daily", ["date"],
    )
    # Required composite index: (entity_type, entity_id, date)
    op.create_index(
        "ix_entity_timeseries_daily_type_entity_date",
        "entity_timeseries_daily", ["entity_type", "entity_id", "date"],
    )

    # ------------------------------------------------------------------
    # 3. market_signals → signals
    #    DESTRUCTIVE: old data is discarded (same UUID cast reason).
    # ------------------------------------------------------------------
    op.drop_index("ix_market_signals_entity_id", table_name="market_signals")
    op.drop_table("market_signals")

    op.create_table(
        "signals",
        _uuid_col("id", nullable=False, server_default=sa.text("gen_random_uuid()")),
        _uuid_col("entity_id", nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("signal_type", sa.String(64), nullable=False),
        sa.Column("strength", sa.Float(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("trigger_value", sa.Float(), nullable=True),
        sa.Column("baseline_value", sa.Float(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entity_id", "entity_type", "signal_type", "detected_at",
            name="uq_signal_entity_type_detected_at",
        ),
    )
    op.create_index("ix_signals_entity_id", "signals", ["entity_id"])
    op.create_index("ix_signals_entity_type", "signals", ["entity_type"])
    op.create_index("ix_signals_signal_type", "signals", ["signal_type"])
    op.create_index("ix_signals_detected_at", "signals", ["detected_at"])
    # Required composite index: (entity_type, entity_id, signal_type, detected_at)
    op.create_index(
        "ix_signals_type_entity_signal_detected",
        "signals", ["entity_type", "entity_id", "signal_type", "detected_at"],
    )

    # ------------------------------------------------------------------
    # 4. brands — DROP (Integer PK) + CREATE (UUID PK)
    #    DESTRUCTIVE: old brand data is discarded.
    # ------------------------------------------------------------------
    op.drop_index("ix_brands_canonical_name", table_name="brands")
    op.drop_table("brands")

    op.create_table(
        "brands",
        _uuid_col("id", nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("country", sa.String(64), nullable=True),
        sa.Column("segment", sa.String(64), nullable=True),
        sa.Column("price_tier", sa.String(64), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_brand_name"),
        sa.UniqueConstraint("slug", name="uq_brand_slug"),
        sa.UniqueConstraint("ticker", name="uq_brand_ticker"),
    )
    op.create_index("ix_brand_name", "brands", ["name"])
    op.create_index("ix_brand_slug", "brands", ["slug"])
    op.create_index("ix_brand_ticker", "brands", ["ticker"])

    # ------------------------------------------------------------------
    # 5. perfumes — DROP (Integer PK, Integer brand_id) + CREATE (UUID PK)
    #    DESTRUCTIVE: old perfume data is discarded.
    # ------------------------------------------------------------------
    op.drop_index("ix_perfumes_brand_id", table_name="perfumes")
    op.drop_index("ix_perfumes_canonical_name", table_name="perfumes")
    op.drop_table("perfumes")

    op.create_table(
        "perfumes",
        _uuid_col("id", nullable=False, server_default=sa.text("gen_random_uuid()")),
        _uuid_col("brand_id", nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("launch_year", sa.Integer(), nullable=True),
        sa.Column("gender_position", sa.String(64), nullable=True),
        sa.Column("olfactive_family", sa.String(128), nullable=True),
        sa.Column("price_band", sa.String(64), nullable=True),
        sa.Column("concentration", sa.String(64), nullable=True),
        sa.Column("notes_summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_perfume_slug"),
        sa.UniqueConstraint("ticker", name="uq_perfume_ticker"),
    )
    op.create_index("ix_perfume_brand_id", "perfumes", ["brand_id"])
    op.create_index("ix_perfume_name", "perfumes", ["name"])
    op.create_index("ix_perfume_slug", "perfumes", ["slug"])
    op.create_index("ix_perfume_ticker", "perfumes", ["ticker"])

    # ------------------------------------------------------------------
    # 6. entity_mentions — DROP (Integer PK, String entity_id) + CREATE
    #    DESTRUCTIVE: old mention data is discarded.
    # ------------------------------------------------------------------
    op.drop_index("ix_entity_mentions_content_item_id", table_name="entity_mentions")
    op.drop_index("ix_entity_mentions_entity_type", table_name="entity_mentions")
    op.drop_index("ix_entity_mentions_entity_id", table_name="entity_mentions")
    op.drop_table("entity_mentions")

    op.create_table(
        "entity_mentions",
        _uuid_col("id", nullable=False, server_default=sa.text("gen_random_uuid()")),
        _uuid_col("entity_id", nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=True),
        sa.Column("source_platform", sa.String(64), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("author_id", sa.String(255), nullable=True),
        sa.Column("author_name", sa.String(255), nullable=True),
        sa.Column("mention_count", sa.Float(), nullable=False, server_default="0"),
        sa.Column("influence_score", sa.Float(), nullable=True),
        sa.Column("sentiment", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("engagement", sa.Float(), nullable=True),
        sa.Column("region", sa.String(64), nullable=True),
        sa.Column("channel", sa.String(64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_entity_mention_entity_id", "entity_mentions", ["entity_id"])
    op.create_index("ix_entity_mention_entity_type", "entity_mentions", ["entity_type"])
    op.create_index("ix_entity_mention_source_type", "entity_mentions", ["source_type"])
    op.create_index("ix_entity_mention_source_platform", "entity_mentions", ["source_platform"])
    op.create_index("ix_entity_mention_author_id", "entity_mentions", ["author_id"])
    op.create_index("ix_entity_mention_region", "entity_mentions", ["region"])
    op.create_index("ix_entity_mention_channel", "entity_mentions", ["channel"])
    op.create_index("ix_entity_mention_occurred_at", "entity_mentions", ["occurred_at"])
    # Required composite index: (entity_type, entity_id, occurred_at)
    op.create_index(
        "ix_entity_mention_type_entity_occurred",
        "entity_mentions", ["entity_type", "entity_id", "occurred_at"],
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    """
    Reverses the structural changes but CANNOT restore any data.

    Data that existed in the v1 tables before this migration was applied
    is permanently gone. After downgrading, the v1 tables will be empty.
    """
    # ------------------------------------------------------------------
    # 6. Restore entity_mentions (Integer PK, String entity_id)
    # ------------------------------------------------------------------
    op.drop_index("ix_entity_mention_type_entity_occurred", table_name="entity_mentions")
    op.drop_index("ix_entity_mention_occurred_at", table_name="entity_mentions")
    op.drop_index("ix_entity_mention_channel", table_name="entity_mentions")
    op.drop_index("ix_entity_mention_region", table_name="entity_mentions")
    op.drop_index("ix_entity_mention_author_id", table_name="entity_mentions")
    op.drop_index("ix_entity_mention_source_platform", table_name="entity_mentions")
    op.drop_index("ix_entity_mention_source_type", table_name="entity_mentions")
    op.drop_index("ix_entity_mention_entity_type", table_name="entity_mentions")
    op.drop_index("ix_entity_mention_entity_id", table_name="entity_mentions")
    op.drop_table("entity_mentions")

    op.create_table(
        "entity_mentions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("entity_id", sa.String(255), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("content_item_id", sa.String(255), nullable=True),
        sa.Column("mention_weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("sentiment", sa.String(32), nullable=True),
        sa.Column("published_at", sa.String(16), nullable=True),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_entity_mentions_entity_id", "entity_mentions", ["entity_id"])
    op.create_index("ix_entity_mentions_entity_type", "entity_mentions", ["entity_type"])
    op.create_index("ix_entity_mentions_content_item_id", "entity_mentions", ["content_item_id"])

    # ------------------------------------------------------------------
    # 5. Restore perfumes (Integer PK, Integer brand_id FK)
    # ------------------------------------------------------------------
    op.drop_index("ix_perfume_ticker", table_name="perfumes")
    op.drop_index("ix_perfume_slug", table_name="perfumes")
    op.drop_index("ix_perfume_name", table_name="perfumes")
    op.drop_index("ix_perfume_brand_id", table_name="perfumes")
    op.drop_table("perfumes")

    op.create_table(
        "perfumes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("brand_id", sa.Integer(), nullable=True),
        sa.Column("canonical_name", sa.String(255), nullable=False),
        sa.Column("normalized_name", sa.String(255), nullable=False),
        sa.Column("entity_id", sa.String(255), nullable=True),
        sa.Column("default_concentration", sa.String(64), nullable=True),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_id", name="uq_perfume_entity_id"),
    )
    op.create_index("ix_perfumes_canonical_name", "perfumes", ["canonical_name"])
    op.create_index("ix_perfumes_brand_id", "perfumes", ["brand_id"])

    # ------------------------------------------------------------------
    # 4. Restore brands (Integer PK, canonical_name)
    # ------------------------------------------------------------------
    op.drop_index("ix_brand_ticker", table_name="brands")
    op.drop_index("ix_brand_slug", table_name="brands")
    op.drop_index("ix_brand_name", table_name="brands")
    op.drop_table("brands")

    op.create_table(
        "brands",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("canonical_name", sa.String(255), nullable=False),
        sa.Column("normalized_name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_name", name="uq_brand_canonical_name"),
    )
    op.create_index("ix_brands_canonical_name", "brands", ["canonical_name"])

    # ------------------------------------------------------------------
    # 3. Restore market_signals (Integer PK, String entity_id, score, details_json)
    # ------------------------------------------------------------------
    op.drop_index("ix_signals_type_entity_signal_detected", table_name="signals")
    op.drop_index("ix_signals_detected_at", table_name="signals")
    op.drop_index("ix_signals_signal_type", table_name="signals")
    op.drop_index("ix_signals_entity_type", table_name="signals")
    op.drop_index("ix_signals_entity_id", table_name="signals")
    op.drop_table("signals")

    op.create_table(
        "market_signals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("entity_id", sa.String(255), nullable=False),
        sa.Column("signal_type", sa.String(64), nullable=False),
        sa.Column("detected_at", sa.String(16), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("details_json", sa.Text(), nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entity_id", "signal_type", "detected_at",
            name="uq_signal_entity_type_date",
        ),
    )
    op.create_index("ix_market_signals_entity_id", "market_signals", ["entity_id"])

    # ------------------------------------------------------------------
    # 2. Restore entity_daily_snapshots (Integer PK, String entity_id)
    # ------------------------------------------------------------------
    op.drop_index("ix_entity_timeseries_daily_type_entity_date", table_name="entity_timeseries_daily")
    op.drop_index("ix_entity_timeseries_daily_date", table_name="entity_timeseries_daily")
    op.drop_index("ix_entity_timeseries_daily_entity_type", table_name="entity_timeseries_daily")
    op.drop_index("ix_entity_timeseries_daily_entity_id", table_name="entity_timeseries_daily")
    op.drop_table("entity_timeseries_daily")

    op.create_table(
        "entity_daily_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("entity_id", sa.String(255), nullable=False),
        sa.Column("date", sa.String(16), nullable=False),
        sa.Column("mention_count", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unique_authors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("engagement_sum", sa.Float(), nullable=False, server_default="0"),
        sa.Column("sentiment_avg", sa.Float(), nullable=True),
        sa.Column("trend_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("composite_market_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("momentum", sa.Float(), nullable=False, server_default="0"),
        sa.Column("acceleration", sa.Float(), nullable=False, server_default="0"),
        sa.Column("volatility", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source_diversity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mentions_prev_day", sa.Float(), nullable=False, server_default="0"),
        sa.Column("growth", sa.Float(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_id", "date", name="uq_snapshot_entity_date"),
    )
    op.create_index(
        "ix_entity_daily_snapshots_entity_id", "entity_daily_snapshots", ["entity_id"]
    )

    # ------------------------------------------------------------------
    # 1. Revert entity_market — restore String entity_id as primary key,
    #    remove UUID id column and created_at.
    # ------------------------------------------------------------------
    op.drop_index("ix_entity_market_entity_id", table_name="entity_market")
    op.drop_constraint("uq_entity_market_entity_id", "entity_market", type_="unique")

    # Restore entity_id as primary key.
    op.drop_constraint("entity_market_pkey", "entity_market", type_="primary")
    op.create_primary_key("entity_market_pkey", "entity_market", ["entity_id"])

    op.drop_column("entity_market", "created_at")
    op.drop_column("entity_market", "id")
