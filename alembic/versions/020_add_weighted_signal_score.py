"""Add weighted_signal_score to entity_timeseries_daily (Phase I2 — Signal Weighting).

Revision ID: 020
Revises: 019
Create Date: 2026-04-24

Changes:
  1. entity_timeseries_daily.weighted_signal_score (Float, nullable) — source-quality-weighted score
  2. Backfill mention_sources.source_score for all existing rows where computable
  3. Backfill weighted_signal_score for all existing timeseries rows using new source_score data
"""

from alembic import op
import sqlalchemy as sa


revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1 — Add weighted_signal_score column
    op.add_column(
        "entity_timeseries_daily",
        sa.Column("weighted_signal_score", sa.Float(), nullable=True),
    )

    # 2 — Backfill mention_sources.source_score for existing rows
    # YouTube: 70% view quality + 30% engagement_rate quality
    # View quality: log10(views+1)/log10(100_000), capped at 1.0
    op.execute("""
        UPDATE mention_sources
        SET source_score = LEAST(1.0,
            0.7 * LEAST(LOG(views + 1) / LOG(100000), 1.0)
            + 0.3 * LEAST(COALESCE(engagement_rate * 10, 0.0), 1.0)
        )
        WHERE platform = 'youtube'
          AND views IS NOT NULL
          AND views > 0
          AND source_score IS NULL
    """)

    # Reddit: 60% upvote quality + 40% comment quality
    # upvote quality: log10(likes+1)/log10(1000), comment: log10(comments_count+1)/log10(100)
    op.execute("""
        UPDATE mention_sources
        SET source_score = LEAST(1.0,
            0.6 * LEAST(LOG(COALESCE(likes, 0) + 1) / LOG(1000), 1.0)
            + 0.4 * LEAST(LOG(COALESCE(comments_count, 0) + 1) / LOG(100), 1.0)
        )
        WHERE platform = 'reddit'
          AND (likes IS NOT NULL OR comments_count IS NOT NULL)
          AND source_score IS NULL
    """)

    # 3 — Backfill weighted_signal_score for all existing timeseries rows
    # Formula: MIN(100, composite_market_score × (1.0 + avg_source_quality))
    # where avg_source_quality = COALESCE(AVG(source_score), 0.0) for entity's mentions on date
    op.execute("""
        UPDATE entity_timeseries_daily etd
        SET weighted_signal_score = LEAST(100.0,
            etd.composite_market_score * (
                1.0 + COALESCE((
                    SELECT AVG(ms.source_score)
                    FROM entity_mentions em
                    JOIN mention_sources ms ON ms.mention_id = em.id
                    WHERE em.entity_id = etd.entity_id
                      AND em.occurred_at::date = etd.date
                      AND ms.source_score IS NOT NULL
                ), 0.0)
            )
        )
        WHERE etd.mention_count > 0
    """)


def downgrade() -> None:
    op.drop_column("entity_timeseries_daily", "weighted_signal_score")
