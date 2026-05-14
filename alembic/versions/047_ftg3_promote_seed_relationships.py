"""FTG-3 / RI1-QA — Promote seed relationships to public.

Revision: 047
Down revision: 046

Purpose:
  All 7 FTG-2 seeded relationships were inserted with is_public=FALSE pending
  FTG-3 operator review gate. They are all operator_reviewed=TRUE and
  confidence_score >= 0.700, so they satisfy the public quality gate.

  This migration (Option A — Controlled Seed Promotion) promotes them to
  is_public=TRUE so that when public reads are switched to the DB-backed path
  in this same phase, existing public entity relationship display is preserved
  without a transitional disappearance of relationship labels.

  No schema changes. Data-only migration.
"""

from alembic import op


# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    """Promote all 7 founder-curated seed relationships to is_public=TRUE.

    Condition: operator_reviewed=TRUE AND confidence_score >= 0.700.
    All 7 seeded rows satisfy this condition; the filter makes the migration
    idempotent and safe to rerun if the table is re-seeded.
    """
    op.execute("""
        UPDATE fragrance_relationships
        SET is_public = TRUE
        WHERE operator_reviewed = TRUE
          AND confidence_score >= 0.700
    """)


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    """Revert: set is_public=FALSE for all rows (back to FTG-2 state)."""
    op.execute("UPDATE fragrance_relationships SET is_public = FALSE")
