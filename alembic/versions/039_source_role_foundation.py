"""Source Role Foundation v1 — source_role + creator_score_eligible on youtube_channels

Revision ID: 039
Revises: 038
Create Date: 2026-05-11

Adds two columns to youtube_channels:

  source_role VARCHAR(64) DEFAULT 'independent_creator'
    Classification of what kind of source this channel is.
    Values (no CHECK constraint — extensible without migration):
      independent_creator   — fragrance reviewer / commentator (default, leaderboard-eligible)
      brand_official        — brand or house's own channel
      retailer_shop         — retailer, shop, or distributor channel
      formulation_education — fragrance formulation / DIY / supplier education channel
      aggregator            — playlist aggregators, compilations, etc.
      unknown               — not yet classified

  creator_score_eligible BOOLEAN DEFAULT TRUE
    Gate for Creator Intelligence leaderboard.
    TRUE  — channel appears in /api/v1/creators leaderboard (default for all existing rows)
    FALSE — channel tracked for content but excluded from leaderboard
            (used for brand_official / retailer / non-creator sources)

No CHECK constraint on source_role — new values can be added by INSERT/UPDATE
without a schema migration.

Backfill: server_default ensures all existing youtube_channels rows receive
  source_role = 'independent_creator'  and  creator_score_eligible = TRUE
automatically via the DEFAULT — no explicit UPDATE needed.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "youtube_channels",
        sa.Column(
            "source_role",
            sa.String(64),
            nullable=True,
            server_default="independent_creator",
        ),
    )
    op.add_column(
        "youtube_channels",
        sa.Column(
            "creator_score_eligible",
            sa.Boolean(),
            nullable=True,
            server_default=sa.text("TRUE"),
        ),
    )
    op.create_index(
        "ix_youtube_channels_source_role",
        "youtube_channels",
        ["source_role"],
    )
    op.create_index(
        "ix_youtube_channels_creator_score_eligible",
        "youtube_channels",
        ["creator_score_eligible"],
    )


def downgrade() -> None:
    op.drop_index("ix_youtube_channels_creator_score_eligible", table_name="youtube_channels")
    op.drop_index("ix_youtube_channels_source_role", table_name="youtube_channels")
    op.drop_column("youtube_channels", "creator_score_eligible")
    op.drop_column("youtube_channels", "source_role")
