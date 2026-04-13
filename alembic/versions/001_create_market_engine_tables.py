"""Create market engine tables (original schema v1)

Revision ID: 001
Revises:
Create Date: 2026-04-10

Creates the initial Market Engine Core tables:

  entity_market            : tracked market entities — entity_id is the String PK
  entity_daily_snapshots   : daily time-series metrics (Integer PK, String entity_id)
  market_signals           : detected signal events (Integer PK, String entity_id)

These tables sit alongside the existing pipeline tables without modifying them.

NOTE: This is the ORIGINAL v1 schema. Migration 003 performs a breaking upgrade
to the v2 schema (UUID PKs, table renames, new columns).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entity_market",
        sa.Column("entity_id", sa.String(255), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("canonical_name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("entity_id"),
    )

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


def downgrade() -> None:
    op.drop_index("ix_market_signals_entity_id", table_name="market_signals")
    op.drop_table("market_signals")
    op.drop_index("ix_entity_daily_snapshots_entity_id", table_name="entity_daily_snapshots")
    op.drop_table("entity_daily_snapshots")
    op.drop_table("entity_market")
