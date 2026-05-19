"""DATA4-C — TOM FORD collection-as-brand hierarchy entries.

Revision: 054
Down revision: 053

Classifies TOM FORD Private Blend and TOM FORD Signature as themed
collections under the Tom Ford parent brand in brand_profiles.

Fragrantica catalogs Tom Ford fragrances across three brand nodes:
  - "Tom Ford"               (parent brand, 134 resolver perfumes)
  - "TOM FORD Private Blend" (luxury/niche collection, 39 resolver perfumes)
  - "TOM FORD Signature"     (mainstream collection, 2 resolver perfumes)

Hierarchy decision:
  TOM FORD Private Blend → collection under tom ford
    Tom Ford's exclusive luxury fragrance collection (Oud Wood, Tobacco Vanille,
    Neroli Portofino, Lost Cherry, etc.). Created by Tom Ford as a curated
    premium tier — not an acquisition, not an independently branded sub-house.
    No standalone brand equity outside of the Tom Ford house. node_type=collection.

  TOM FORD Signature → collection under tom ford
    Tom Ford's mainstream/accessible fragrance tier (Ombré Leather, etc.).
    A product line classification within the Tom Ford catalog. node_type=collection.

Note on duplicate entity exposure:
  Some products (Ombré Leather, Oud Wood, Neroli Portofino) appear in
  entity_market under BOTH "Tom Ford" and "TOM FORD Private Blend" brand_name
  values — each maps to a separate Fragrantica resolver entry. This dedup issue
  is out of scope for DATA4-C (display/hierarchy only). Deduplication is
  addressed in DATA4-E (systemic brand_name canonicalization).

No schema changes. No rollup changes. No URL changes. Display layer only.
"""

from alembic import op
import sqlalchemy as sa


revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Seed rows — DATA4-C Tom Ford hierarchy
# (brand_name_normalized, brand_tier, node_type, parent_brand_normalized, notes)
# ---------------------------------------------------------------------------

_TF_HIERARCHY_SEED = [
    (
        "tom ford private blend",
        "designer",
        "collection",
        "tom ford",
        "Tom Ford's exclusive luxury fragrance collection (Oud Wood, Tobacco Vanille, "
        "Neroli Portofino, Lost Cherry, etc.). Premium tier within the Tom Ford house; "
        "not an independent brand or acquisition.",
    ),
    (
        "tom ford signature",
        "designer",
        "collection",
        "tom ford",
        "Tom Ford's mainstream fragrance tier (Ombré Leather, Metallique, etc.). "
        "Product-line classification within the Tom Ford catalog; no independent "
        "brand identity.",
    ),
]


def upgrade() -> None:
    conn = op.get_bind()

    # Ensure parent 'tom ford' row exists — already seeded in migration 044
    # with brand_tier='designer', but guard defensively.
    conn.execute(
        sa.text(
            "INSERT INTO brand_profiles (brand_name_normalized, brand_tier) "
            "VALUES ('tom ford', 'designer') "
            "ON CONFLICT (brand_name_normalized) DO NOTHING"
        )
    )

    # Insert collection rows — ON CONFLICT updates node_type + parent_brand_normalized
    # in case the row was already seeded with node_type='brand'.
    for norm, tier, node_type, parent, notes in _TF_HIERARCHY_SEED:
        conn.execute(
            sa.text(
                "INSERT INTO brand_profiles "
                "  (brand_name_normalized, brand_tier, node_type, parent_brand_normalized, notes) "
                "VALUES (:n, :t, :nt, :p, :notes) "
                "ON CONFLICT (brand_name_normalized) DO UPDATE "
                "  SET node_type = EXCLUDED.node_type, "
                "      parent_brand_normalized = EXCLUDED.parent_brand_normalized, "
                "      notes = COALESCE(brand_profiles.notes, EXCLUDED.notes)"
            ),
            {"n": norm, "t": tier, "nt": node_type, "p": parent, "notes": notes},
        )


def downgrade() -> None:
    conn = op.get_bind()
    # Remove the hierarchy classification (revert to node_type='brand', no parent)
    for norm, _, _, _, _ in _TF_HIERARCHY_SEED:
        conn.execute(
            sa.text(
                "UPDATE brand_profiles "
                "SET node_type = 'brand', parent_brand_normalized = NULL "
                "WHERE brand_name_normalized = :n"
            ),
            {"n": norm},
        )
