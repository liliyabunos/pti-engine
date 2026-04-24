"""Add trend_state to entity_timeseries_daily (Phase I3 — Trend State Layer).

Revision ID: 021
Revises: 020
Create Date: 2026-04-24

Changes:
  entity_timeseries_daily.trend_state (VARCHAR 20, nullable)

  Possible values: 'breakout' | 'rising' | 'peak' | 'stable' | 'declining' | 'emerging'
  NULL = carry-forward row (mention_count == 0) or not yet computed.

  Populated by _compute_trend_states() in aggregate_daily_market_metrics.py
  after each daily aggregation run.
"""

from alembic import op
import sqlalchemy as sa


revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "entity_timeseries_daily",
        sa.Column("trend_state", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("entity_timeseries_daily", "trend_state")
