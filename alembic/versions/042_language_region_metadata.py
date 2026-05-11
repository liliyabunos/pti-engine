"""Phase 042 — Language & Region Metadata v1

Revision ID: 042
Revises: 041
Create Date: 2026-05-11

Adds first-class language and region metadata columns to source intake and
youtube_channels.  Metadata only — no scoring, no leaderboard changes.

source_intake_candidates additions:
  source_language        VARCHAR(16) NULL  — e.g. 'en', 'es', 'ar'
  source_country         VARCHAR(8)  NULL  — e.g. 'US', 'ES', 'AE'
  source_region          VARCHAR(64) NULL  — normalized region bucket
  audience_region        VARCHAR(64) NULL  — intended audience region
  regional_policy_status VARCHAR(64) NULL  — policy decision status

youtube_channels additions:
  source_region          VARCHAR(64) NULL
  audience_region        VARCHAR(64) NULL
  regional_policy_status VARCHAR(64) NULL

No CHECK constraints.  Values are carry-forward from candidates at apply time.

Source role and creator leaderboard eligibility are unchanged by this migration.
Creator Leaderboard still gated solely on creator_score_eligible IS NOT FALSE.

Suggested region values (not enforced by DB):
  US_CANADA, UK_IRELAND, EU_DACH, EU_FRANCOPHONE, EU_SOUTH, LATAM, BRAZIL,
  MIDDLE_EAST_GCC, SOUTH_ASIA, EAST_ASIA, SOUTHEAST_ASIA, GLOBAL_ENGLISH, UNKNOWN

Suggested regional_policy_status values (not enforced by DB):
  approved_global, approved_regional, regional_policy_pending,
  excluded_from_global, needs_operator_review, unknown

Downgrade: drops all eight columns.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- source_intake_candidates: language + country + region metadata ---
    with op.batch_alter_table("source_intake_candidates") as batch_op:
        batch_op.add_column(sa.Column("source_language", sa.String(16), nullable=True))
        batch_op.add_column(sa.Column("source_country", sa.String(8), nullable=True))
        batch_op.add_column(sa.Column("source_region", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("audience_region", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("regional_policy_status", sa.String(64), nullable=True))

    # --- youtube_channels: region metadata (source_language/country already exist) ---
    with op.batch_alter_table("youtube_channels") as batch_op:
        batch_op.add_column(sa.Column("source_region", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("audience_region", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("regional_policy_status", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("youtube_channels") as batch_op:
        batch_op.drop_column("regional_policy_status")
        batch_op.drop_column("audience_region")
        batch_op.drop_column("source_region")

    with op.batch_alter_table("source_intake_candidates") as batch_op:
        batch_op.drop_column("regional_policy_status")
        batch_op.drop_column("audience_region")
        batch_op.drop_column("source_region")
        batch_op.drop_column("source_country")
        batch_op.drop_column("source_language")
