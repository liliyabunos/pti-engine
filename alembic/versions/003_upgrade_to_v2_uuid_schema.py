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
3. market_signals → (DROP + CREATE as signals)
4. brands → (DROP + CREATE, UUID PK)
5. perfumes → (DROP + CREATE, UUID PK)
6. entity_mentions → (DROP + CREATE, UUID PK)

== Idempotency ==

All existence checks use direct SQL against information_schema.tables.
This avoids SQLAlchemy Inspector caching issues that occur when the same
connection object is reused across multiple inspect() calls within one
Alembic transactional DDL context.

Pattern for every table in Phase C:
  1. Check information_schema — if table absent, CREATE TABLE
  2. Check information_schema again — if table present, CREATE INDEX IF NOT EXISTS

== PostgreSQL requirement ==

Uses gen_random_uuid() (built-in since PostgreSQL 13).
Not compatible with SQLite.
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


def _table_exists(bind, table_name: str) -> bool:
    """Check live DB state via SQL — never uses SQLAlchemy Inspector cache."""
    result = bind.execute(sa.text(
        "SELECT EXISTS ("
        "  SELECT 1 FROM information_schema.tables"
        "  WHERE table_schema = 'public' AND table_name = :name"
        ")"
    ), {"name": table_name})
    return bool(result.scalar())


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    bind = op.get_bind()

    # ======================================================================
    # PHASE A — Alter entity_market in-place (idempotent)
    # ======================================================================

    op.execute(
        "ALTER TABLE entity_market ADD COLUMN IF NOT EXISTS "
        "id UUID DEFAULT gen_random_uuid()"
    )
    op.execute("UPDATE entity_market SET id = gen_random_uuid() WHERE id IS NULL")
    op.execute("ALTER TABLE entity_market ALTER COLUMN id SET NOT NULL")

    # Swap PK from entity_id → id only if still on entity_id
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

    # Unique constraint on entity_id
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
        "ALTER TABLE entity_market ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ"
    )
    op.execute("UPDATE entity_market SET created_at = NOW() WHERE created_at IS NULL")
    op.execute("ALTER TABLE entity_market ALTER COLUMN created_at SET NOT NULL")

    # ======================================================================
    # PHASE B — Drop old tables / indexes (all IF EXISTS)
    # ======================================================================

    op.execute("DROP INDEX IF EXISTS ix_entity_daily_snapshots_entity_id")
    op.execute("DROP TABLE IF EXISTS entity_daily_snapshots")

    op.execute("DROP INDEX IF EXISTS ix_market_signals_entity_id")
    op.execute("DROP TABLE IF EXISTS market_signals")

    op.execute("DROP INDEX IF EXISTS ix_brands_canonical_name")
    op.execute("DROP TABLE IF EXISTS brands CASCADE")

    op.execute("DROP INDEX IF EXISTS ix_perfumes_brand_id")
    op.execute("DROP INDEX IF EXISTS ix_perfumes_canonical_name")
    op.execute("DROP TABLE IF EXISTS perfumes CASCADE")

    op.execute("DROP INDEX IF EXISTS ix_entity_mentions_content_item_id")
    op.execute("DROP INDEX IF EXISTS ix_entity_mentions_entity_type")
    op.execute("DROP INDEX IF EXISTS ix_entity_mentions_entity_id")
    op.execute("DROP TABLE IF EXISTS entity_mentions")

    # ======================================================================
    # PHASE C — CREATE new tables + indexes
    #
    # Each block:
    #   1. _table_exists() before  → CREATE TABLE if absent
    #   2. _table_exists() after   → CREATE INDEX IF NOT EXISTS if present
    #
    # _table_exists() queries information_schema directly every call —
    # no SQLAlchemy Inspector caching involved.
    # ======================================================================

    # ------------------------------------------------------------------
    # entity_timeseries_daily
    # ------------------------------------------------------------------
    if not _table_exists(bind, "entity_timeseries_daily"):
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

    if _table_exists(bind, "entity_timeseries_daily"):
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
    # signals
    # ------------------------------------------------------------------
    if not _table_exists(bind, "signals"):
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

    if _table_exists(bind, "signals"):
        op.execute("CREATE INDEX IF NOT EXISTS ix_signals_entity_id ON signals (entity_id)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_signals_entity_type ON signals (entity_type)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_signals_signal_type ON signals (signal_type)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_signals_detected_at ON signals (detected_at)")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_signals_type_entity_signal_detected "
            "ON signals (entity_type, entity_id, signal_type, detected_at)"
        )

    # ------------------------------------------------------------------
    # brands
    # ------------------------------------------------------------------
    if not _table_exists(bind, "brands"):
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

    if _table_exists(bind, "brands"):
        op.execute("CREATE INDEX IF NOT EXISTS ix_brand_name ON brands (name)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_brand_slug ON brands (slug)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_brand_ticker ON brands (ticker)")

    # ------------------------------------------------------------------
    # perfumes (must follow brands — FK dependency)
    # ------------------------------------------------------------------
    if not _table_exists(bind, "perfumes"):
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

    if _table_exists(bind, "perfumes"):
        op.execute("CREATE INDEX IF NOT EXISTS ix_perfume_brand_id ON perfumes (brand_id)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_perfume_name ON perfumes (name)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_perfume_slug ON perfumes (slug)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_perfume_ticker ON perfumes (ticker)")

    # ------------------------------------------------------------------
    # entity_mentions
    # ------------------------------------------------------------------
    if not _table_exists(bind, "entity_mentions"):
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

    if _table_exists(bind, "entity_mentions"):
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
    """Reverses structural changes. Data is NOT restored."""

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
