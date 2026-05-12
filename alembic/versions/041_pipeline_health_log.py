"""Pipeline Health Log — pipeline_health_log table for persisted health history

Revision ID: 041
Revises: 040
Create Date: 2026-05-11

Creates pipeline_health_log to persist the output of pipeline_health_check.py
after every morning and evening pipeline run.

Retention: 90 days, trimmed inside the health check job (no separate cron needed).

Idempotent upsert: ON CONFLICT (run_date, run_label) DO UPDATE — re-running the
same health check for the same date+label overwrites the row without duplicating.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_health_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        # --- Run identity ---
        sa.Column("run_date", sa.Date, nullable=False),
        sa.Column("run_label", sa.String(32), nullable=False),   # morning|evening|manual|backfill|unknown
        # --- Result ---
        sa.Column("overall_level", sa.String(16), nullable=False),  # OK|WARNING|CRITICAL
        # --- Metrics snapshot ---
        sa.Column("entity_mentions", sa.Integer, nullable=False),
        sa.Column("reddit_mentions", sa.Integer, nullable=False),
        sa.Column("youtube_items", sa.Integer, nullable=False),
        sa.Column("reddit_items", sa.Integer, nullable=False),
        sa.Column("total_items", sa.Integer, nullable=False),
        sa.Column("signals_count", sa.Integer, nullable=False),
        # --- Detail ---
        sa.Column("issues", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        # --- Context ---
        sa.Column("pipeline_service", sa.String(64), nullable=True),  # Railway service name or execution context
        sa.Column(
            "recorded_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # Primary query path: recent runs by date
    op.create_index(
        "ix_pipeline_health_log_run_date",
        "pipeline_health_log",
        ["run_date"],
    )

    # Filter by level for alerting queries
    op.create_index(
        "ix_pipeline_health_log_level",
        "pipeline_health_log",
        ["overall_level", "run_date"],
    )

    # Unique constraint: one row per (date, run_label) — enables idempotent upsert
    op.create_unique_constraint(
        "uq_pipeline_health_log_date_run",
        "pipeline_health_log",
        ["run_date", "run_label"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_pipeline_health_log_date_run", "pipeline_health_log", type_="unique")
    op.drop_index("ix_pipeline_health_log_level", table_name="pipeline_health_log")
    op.drop_index("ix_pipeline_health_log_run_date", table_name="pipeline_health_log")
    op.drop_table("pipeline_health_log")
