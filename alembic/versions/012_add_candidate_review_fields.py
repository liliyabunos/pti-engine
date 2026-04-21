"""Add Phase 4a review fields to fragrance_candidates.

Revision ID: 012
Revises: 011
Create Date: 2026-04-21

Adds structured review/approval workflow fields to fragrance_candidates.
Phase 4a only — no writes to fragrance_master, aliases, or brands.

New columns:
  review_status            — pending_review | approved_for_promotion |
                             rejected_final | needs_normalization
  normalized_candidate_text — cleaned promotion-ready form of the phrase
                             (nullable; set when text needs context-stripping)
  reviewed_at              — ISO timestamp of last review action (nullable)
  review_notes             — free-text annotation from reviewer (nullable)
  approved_entity_type     — perfume | brand | note | unknown (nullable)
                             filled on approval to declare intended KB type
"""

from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fragrance_candidates",
        sa.Column(
            "review_status",
            sa.Text(),
            nullable=False,
            server_default="pending_review",
        ),
    )
    op.add_column(
        "fragrance_candidates",
        sa.Column("normalized_candidate_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "fragrance_candidates",
        sa.Column("reviewed_at", sa.Text(), nullable=True),
    )
    op.add_column(
        "fragrance_candidates",
        sa.Column("review_notes", sa.Text(), nullable=True),
    )
    op.add_column(
        "fragrance_candidates",
        sa.Column("approved_entity_type", sa.Text(), nullable=True),
    )

    op.create_index(
        "ix_fragrance_candidates_review_status",
        "fragrance_candidates",
        ["review_status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_fragrance_candidates_review_status",
        table_name="fragrance_candidates",
    )
    op.drop_column("fragrance_candidates", "approved_entity_type")
    op.drop_column("fragrance_candidates", "review_notes")
    op.drop_column("fragrance_candidates", "reviewed_at")
    op.drop_column("fragrance_candidates", "normalized_candidate_text")
    op.drop_column("fragrance_candidates", "review_status")
