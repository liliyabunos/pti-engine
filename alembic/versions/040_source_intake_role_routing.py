"""Source Intake Role Routing v1 — source_role + creator_score_eligible on source_intake_candidates

Revision ID: 040
Revises: 039
Create Date: 2026-05-11

Adds two nullable columns to source_intake_candidates:

  source_role VARCHAR(64) NULL
    Operator-assigned classification before apply.
    Values: independent_creator | brand_official | retailer_shop |
            formulation_education | aggregator | unknown
    NULL = not yet assigned; resolved to 'independent_creator' at apply time.
    No CHECK constraint — extensible without future migration.

  creator_score_eligible BOOLEAN NULL
    Explicit override for leaderboard eligibility.
    NULL = derive from source_role at apply time:
      independent_creator → True
      all others → False
"""

from alembic import op
import sqlalchemy as sa


revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("source_intake_candidates") as batch_op:
        batch_op.add_column(
            sa.Column("source_role", sa.String(64), nullable=True, server_default=None)
        )
        batch_op.add_column(
            sa.Column("creator_score_eligible", sa.Boolean, nullable=True, server_default=None)
        )


def downgrade() -> None:
    with op.batch_alter_table("source_intake_candidates") as batch_op:
        batch_op.drop_column("creator_score_eligible")
        batch_op.drop_column("source_role")
