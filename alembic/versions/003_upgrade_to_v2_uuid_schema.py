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

3. market_signals → (DROP + CREATE as signals)
   - REASON: same as above.

4. brands → (DROP + CREATE)
   - REASON: Integer PK cannot be safely cast to UUID. Data is DISCARDED.

5. perfumes → (DROP + CREATE)
   - REASON: Integer PK and Integer brand_id FK cannot be safely cast to UUID.

6. entity_mentions → (DROP + CREATE)
   - REASON: Integer PK and String entity_id cannot be safely cast to UUID.

== Idempotency ==

upgrade() is structured in three explicit phases:

  Phase A — ALTER entity_market (ADD COLUMN IF NOT EXISTS, conditional PK swap)
  Phase B — DROP all old/interim tables and indexes (all IF EXISTS)
  Phase C — inspect() AFTER drops, then CREATE tables not yet present,
             then CREATE INDEX IF NOT EXISTS

By inspecting after the drops, the existence snapshot is always accurate
regardless of how far a prior partial run got. This makes the migration safe
to re-run on a fresh DB, a partially-applied DB, or after a mid-deploy crash.

== PostgreSQL requirement ==

This migration uses gen_random_uuid() and PostgreSQL-native UUID type.
It is NOT compatible with SQLite.
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
    return sa.Column(name, postgresql.UUID(as_uuid=True), **kwargs)


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    bind = op.get_bind()

    # ======================================================================
    # PHASE A — Alter entity_market in-place (idempotent column additions)
    # ======================================================================

    # Add UUID id column if not already there.
    op.execute(
        "ALTER TABLE entity_market ADD COLUMN IF NOT EXISTS "
        "id UUID DEFAULT gen_random_uuid()"
    )
    op.execute("UPDATE entity_market SET id = gen_random_uuid() WHERE id IS NULL")
    op.execute("ALTER TABLE entity_market ALTER COLUMN id SET NOT NULL")

    # Swap primary key from entity_id → id only if still on entity_id.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_attribute a
                  ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
                WHERE c.contype = 'p'
                  AND c.conrelid = 'entity_market'::regclass
                  AND a.attname = 'entity_id'
            ) THEN
                ALTER TABLE entity_market DROP CONSTRAINT entity_market_pkey;
                ALTER TABLE entity_market ADD CONSTRAINT entity_market_pkey PRIMARY KEY (id);
            END IF;
        END $$;
    """)

    # Unique constraint on entity_id (safe if already exists).
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_entity_market_entity_id'
                  AND conrelid = 'entity_market'::regclass
            ) THEN
                ALTER TABLE entity_market
                    ADD CONSTRAINT uq_entity_market_entity_id UNIQUE (entity_id);
            END IF;
        END $$;
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_entity_market_entity_id "
        "ON entity_market (entity_id)"
    )

    op.execute(
        "ALTER TABLE entity_market ADD COLUMN IF NOT EXISTS "
        "created_at TIMESTAMPTZ"
    )
    op.execute("UPDATE entity_market SET created_at = NOW() WHERE created_at IS NULL")
    op.execute("ALTER TABLE entity_market ALTER COLUMN created_at SET NOT NULL")

    # ======================================================================
    # PHASE B — Drop all old/interim tables and indexes (IF EXISTS throughout)
    #
    # Done before inspection so that Phase C sees accurate post-drop state.
    # ======================================================================

    # entity_daily_snapshots (old name for entity_timeseries_daily)
    op.execute("DROP INDEX IF EXISTS ix_entity_daily_snapshots_entity_id")
    op.execute("DROP TABLE IF EXISTS entity_daily_snapshots")

    # market_signals (old name for signals)
    op.execute("DROP INDEX IF EXISTS ix_market_signals_entity_id")
    op.execute("DROP TABLE IF EXISTS market_signals")

    # brands — CASCADE because perfumes may FK to it
    op.execute("DROP INDEX IF EXISTS ix_brands_canonical_name")
    op.execute("DROP TABLE IF EXISTS brands CASCADE")

    # perfumes — CASCADE in case anything FKs to it
    op.execute("DROP INDEX IF EXISTS ix_perfumes_brand_id")
    op.execute("DROP INDEX IF EXISTS ix_perfumes_canonical_name")
    op.execute("DROP TABLE IF EXISTS perfumes CASCADE")

    # entity_mentions
    op.execute("DROP INDEX IF EXISTS ix_entity_mentions_content_item_id")
    op.execute("DROP INDEX IF EXISTS ix_entity_mentions_entity_type")
    op.execute("DROP INDEX IF EXISTS ix_entity_mentions_entity_id")
    op.execute("DROP TABLE IF EXISTS entity_mentions")

    # ======================================================================
    # PHASE C — Inspect AFTER drops, then CREATE missing tables + indexes
    #
    # Inspecting here (not at function start) gives us the true post-drop
    # picture: tables dropped above will not appear in `existing`, so their
    # CREATE TABLE blocks will always run as needed.
    # ======================================================================

    existing = set(sa.inspect(bind).get_table_names())

    # ------------------------------------------------------------------
    # entity_timeseries_daily (replaces entity_daily_snapshots)
    # ------------------------------------------------------------------
    if "entity_timeseries_daily" not in existing:
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

    if "entity_timeseries_daily" in existing:
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_entity_timeseries_daily_entity_id "
            "ON entity_timeseries_daily (entity_id)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_entity_timeseries_daily_entity_type "
            "ON entity_timeseries_daily (entity_type)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_entity_timeseries_daily_date "
            "ON entity_timeseries_daily (date)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_entity_timeseries_daily_type_entity_date "
            "ON entity_timeseries_daily (entity_type, entity_id, date)"
        )

    # ------------------------------------------------------------------
    # signals (replaces market_signals)
    # ------------------------------------------------------------------
    if "signals" not in existing:
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

    if "signals" in existing:
        op.execute("CREATE INDEX IF NOT EXISTS ix_signals_entity_id ON signals (entity_id)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_signals_entity_type ON signals (entity_type)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_signals_signal_type ON signals (signal_type)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_signals_detected_at ON signals (detected_at)")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_signals_type_entity_signal_detected "
            "ON signals (entity_type, entity_id, signal_type, detected_at)"
        )

    # ------------------------------------------------------------------
    # brands (v2 UUID schema)
    # ------------------------------------------------------------------
    if "brands" not in existing:
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

    if "brands" in existing:
        op.execute("CREATE INDEX IF NOT EXISTS ix_brand_name ON brands (name)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_brand_slug ON brands (slug)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_brand_ticker ON brands (ticker)")

    # ------------------------------------------------------------------
    # perfumes (v2 UUID schema) — must come after brands (FK dependency)
    # ------------------------------------------------------------------
    if "perfumes" not in existing:
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

    if "perfumes" in existing:
        op.execute("CREATE INDEX IF NOT EXISTS ix_perfume_brand_id ON perfumes (brand_id)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_perfume_name ON perfumes (name)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_perfume_slug ON perfumes (slug)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_perfume_ticker ON perfumes (ticker)")

    # ------------------------------------------------------------------
    # entity_mentions (v2 UUID schema)
    # ------------------------------------------------------------------
    if "entity_mentions" not in existing:
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

    if "entity_mentions" in existing:
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_entity_mention_entity_id "
            "ON entity_mentions (entity_id)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_entity_mention_entity_type "
            "ON entity_mentions (entity_type)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_entity_mention_source_type "
            "ON entity_mentions (source_type)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_entity_mention_source_platform "
            "ON entity_mentions (source_platform)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_entity_mention_author_id "
            "ON entity_mentions (author_id)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_entity_mention_region "
            "ON entity_mentions (region)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_entity_mention_channel "
            "ON entity_mentions (channel)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_entity_mention_occurred_at "
            "ON entity_mentions (occurred_at)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_entity_mention_type_entity_occurred "
            "ON entity_mentions (entity_type, entity_id, occurred_at)"
        )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    """
    Reverses the structural changes but CANNOT restore any data.
    """
    # entity_mentions
    op.execute("DROP INDEX IF EXISTS ix_entity_mention_type_entity_occurred")
    op.execute("DROP INDEX IF EXISTS ix_entity_mention_occurred_at")
    op.execute("DROP INDEX IF EXISTS ix_entity_mention_channel")
    op.execute("DROP INDEX IF EXISTS ix_entity_mention_region")
    op.execute("DROP INDEX IF EXISTS ix_entity_mention_author_id")
    op.execute("DROP INDEX IF EXISTS ix_entity_mention_source_platform")
    op.execute("DROP INDEX IF EXISTS ix_entity_mention_source_type")
    op.execute("DROP INDEX IF EXISTS ix_entity_mention_entity_type")
    op.execute("DROP INDEX IF EXISTS ix_entity_mention_entity_id")
    op.execute("DROP TABLE IF EXISTS entity_mentions")

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

    # perfumes
    op.execute("DROP INDEX IF EXISTS ix_perfume_ticker")
    op.execute("DROP INDEX IF EXISTS ix_perfume_slug")
    op.execute("DROP INDEX IF EXISTS ix_perfume_name")
    op.execute("DROP INDEX IF EXISTS ix_perfume_brand_id")
    op.execute("DROP TABLE IF EXISTS perfumes")

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

    # brands
    op.execute("DROP INDEX IF EXISTS ix_brand_ticker")
    op.execute("DROP INDEX IF EXISTS ix_brand_slug")
    op.execute("DROP INDEX IF EXISTS ix_brand_name")
    op.execute("DROP TABLE IF EXISTS brands")

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

    # signals
    op.execute("DROP INDEX IF EXISTS ix_signals_type_entity_signal_detected")
    op.execute("DROP INDEX IF EXISTS ix_signals_detected_at")
    op.execute("DROP INDEX IF EXISTS ix_signals_signal_type")
    op.execute("DROP INDEX IF EXISTS ix_signals_entity_type")
    op.execute("DROP INDEX IF EXISTS ix_signals_entity_id")
    op.execute("DROP TABLE IF EXISTS signals")

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

    # entity_timeseries_daily
    op.execute("DROP INDEX IF EXISTS ix_entity_timeseries_daily_type_entity_date")
    op.execute("DROP INDEX IF EXISTS ix_entity_timeseries_daily_date")
    op.execute("DROP INDEX IF EXISTS ix_entity_timeseries_daily_entity_type")
    op.execute("DROP INDEX IF EXISTS ix_entity_timeseries_daily_entity_id")
    op.execute("DROP TABLE IF EXISTS entity_timeseries_daily")

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

    # entity_market — restore entity_id as PK, drop UUID columns
    op.execute("DROP INDEX IF EXISTS ix_entity_market_entity_id")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_entity_market_entity_id'
                  AND conrelid = 'entity_market'::regclass
            ) THEN
                ALTER TABLE entity_market DROP CONSTRAINT uq_entity_market_entity_id;
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE entity_market DROP CONSTRAINT entity_market_pkey")
    op.execute(
        "ALTER TABLE entity_market ADD CONSTRAINT entity_market_pkey PRIMARY KEY (entity_id)"
    )
    op.execute("ALTER TABLE entity_market DROP COLUMN IF EXISTS created_at")
    op.execute("ALTER TABLE entity_market DROP COLUMN IF EXISTS id")
