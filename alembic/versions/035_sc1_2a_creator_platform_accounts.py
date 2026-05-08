"""SC1.2A — creator_platform_accounts + creator_watchlist_audit_log

Revision ID: 035
Revises: 034
Create Date: 2026-05-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── creator_platform_accounts ──────────────────────────────────────────
    # Platform-neutral creator account registry.
    # For SC1.2 TikTok: rows where platform='tiktok', source_method='manual_seed'.
    # Designed to hold YouTube, TikTok, Instagram, Reddit accounts in future.
    op.create_table(
        "creator_platform_accounts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        # Platform identity
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("platform_handle", sa.String(255), nullable=False),
        sa.Column("platform_url", sa.Text, nullable=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        # Optional link to unified creator identity (future SC0.1)
        sa.Column("creator_id", sa.String(255), nullable=True),
        # Classification
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("tier", sa.String(32), nullable=True),
        # Lifecycle
        sa.Column("status", sa.String(32), nullable=False, server_default="pending_review"),
        sa.Column("seed_source", sa.String(255), nullable=True),
        sa.Column("source_method", sa.String(64), nullable=False, server_default="manual_seed"),
        sa.Column("confidence", sa.Float, nullable=True),
        # Metrics (updated by enrichment worker, nullable until first fetch)
        sa.Column("follower_count", sa.BigInteger, nullable=True),
        sa.Column("avg_views", sa.Float, nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_new_content_at", sa.DateTime(timezone=True), nullable=True),
        # Operator metadata
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
    )

    # Uniqueness: one row per (platform, handle)
    op.create_index(
        "uq_creator_platform_accounts_platform_handle",
        "creator_platform_accounts",
        ["platform", "platform_handle"],
        unique=True,
    )

    # Status index for efficient listing
    op.create_index(
        "ix_creator_platform_accounts_platform_status",
        "creator_platform_accounts",
        ["platform", "status"],
    )

    # ── creator_watchlist_audit_log ────────────────────────────────────────
    op.create_table(
        "creator_watchlist_audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("platform_handle", sa.String(255), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("old_status", sa.String(32), nullable=True),
        sa.Column("new_status", sa.String(32), nullable=True),
        sa.Column("source_method", sa.String(64), nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
    )

    op.create_index(
        "ix_creator_watchlist_audit_log_platform_handle",
        "creator_watchlist_audit_log",
        ["platform", "platform_handle"],
    )


def downgrade() -> None:
    op.drop_index("ix_creator_watchlist_audit_log_platform_handle",
                  table_name="creator_watchlist_audit_log")
    op.drop_table("creator_watchlist_audit_log")
    op.drop_index("ix_creator_platform_accounts_platform_status",
                  table_name="creator_platform_accounts")
    op.drop_index("uq_creator_platform_accounts_platform_handle",
                  table_name="creator_platform_accounts")
    op.drop_table("creator_platform_accounts")
