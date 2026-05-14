"""FTG-1 taxonomy correction — Zara: celebrity → mass_market

Revision ID: 045
Revises: 044
Create Date: 2026-05-14

Corrects a misclassification in the FTG-1 seed (migration 044).

Zara was seeded as brand_tier='celebrity' because Zara Red Temptation is a
known BR540 alternative. However Zara is not a celebrity fragrance brand —
it is a mass-market fashion retailer with a fragrance line.

This migration:
  1. Adds 'mass_market' to the conceptual taxonomy (no schema change required;
     brand_tier is VARCHAR(32) with no CHECK constraint).
  2. Reclassifies brand_name_normalized='zara' from 'celebrity' to 'mass_market'.

Taxonomy after this correction:
  designer     — major designer / luxury conglomerate house (Dior, Chanel, ...)
  niche        — independent/niche house (Creed, MFK, Byredo, ...)
  clone_house  — mass-market clone brand (Armaf, Lattafa, ...)
  celebrity    — celebrity-brand fragrance line (Ariana Grande)
  indie        — small independent house (reserved; not seeded in v1)
  mass_market  — mass-market fashion/retail fragrance label (Zara, ...)

entity_role impact: mass_market → 'unknown' (same as clone_house/celebrity in v1;
no specific entity role assigned to mass_market yet).
Zara Red Temptation's entity_role is dupe_alternative from the dupe map,
which fires before brand-level lookup — unaffected.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE brand_profiles "
            "SET brand_tier = 'mass_market' "
            "WHERE brand_name_normalized = 'zara' "
            "  AND brand_tier = 'celebrity'"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE brand_profiles "
            "SET brand_tier = 'celebrity' "
            "WHERE brand_name_normalized = 'zara' "
            "  AND brand_tier = 'mass_market'"
        )
    )
