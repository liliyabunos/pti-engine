"""Add Phase 4b promotion traceability fields to fragrance_candidates.

Revision ID: 013
Revises: 012
Create Date: 2026-04-21

Adds promotion outcome fields to fragrance_candidates.
These record the result of Phase 4b promotion attempts — they are
written by promote_candidates job and are never modified by Phase 3.

New columns:
  promotion_decision       — exact_existing_entity | merge_into_existing |
                             create_new_entity | reject_promotion
  promoted_at              — ISO timestamp of promotion action (nullable)
  promoted_canonical_name  — canonical name of the target / created entity (nullable)
  promoted_as              — perfume | brand | alias | none (nullable)
  promotion_rejection_reason — reason string when promotion is rejected (nullable)
"""

from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fragrance_candidates",
        sa.Column("promotion_decision", sa.Text(), nullable=True),
    )
    op.add_column(
        "fragrance_candidates",
        sa.Column("promoted_at", sa.Text(), nullable=True),
    )
    op.add_column(
        "fragrance_candidates",
        sa.Column("promoted_canonical_name", sa.Text(), nullable=True),
    )
    op.add_column(
        "fragrance_candidates",
        sa.Column("promoted_as", sa.Text(), nullable=True),
    )
    op.add_column(
        "fragrance_candidates",
        sa.Column("promotion_rejection_reason", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_fragrance_candidates_promotion_decision",
        "fragrance_candidates",
        ["promotion_decision"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_fragrance_candidates_promotion_decision",
        table_name="fragrance_candidates",
    )
    op.drop_column("fragrance_candidates", "promotion_rejection_reason")
    op.drop_column("fragrance_candidates", "promoted_as")
    op.drop_column("fragrance_candidates", "promoted_canonical_name")
    op.drop_column("fragrance_candidates", "promoted_at")
    op.drop_column("fragrance_candidates", "promotion_decision")
