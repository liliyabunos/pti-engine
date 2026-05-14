"""KB-CAT1-B — brand_profiles hierarchy extension.

Revision: 048
Down revision: 047

Adds two columns to brand_profiles:
  node_type VARCHAR(32) NOT NULL DEFAULT 'brand'
    CHECK (node_type IN ('brand', 'collection', 'sub_brand'))
    Values: 'brand' | 'collection' | 'sub_brand'
  parent_brand_normalized TEXT NULL
    No FK constraint. Canonical integrity enforced by operator review.
    Matches brand_name_normalized of the parent row when set.

All existing rows receive node_type='brand', parent_brand_normalized=NULL
via DEFAULT / server_default — no explicit backfill statement needed.

Seeds the 4 confirmed KB-CAT1-A hierarchy candidates:
  Xerjoff - Join the Club  → collection under xerjoff
  Xerjoff - Casamorati     → sub_brand under xerjoff
  Xerjoff - XJ Oud Attars  → collection under xerjoff
  Filippo Sorcinelli - SAUF → collection under filippo sorcinelli

Note on Filippo Sorcinelli - SAUF:
  Official current Filippo Sorcinelli navigation presents this fragrance
  family as "Extrait de Musique"; "SAUF" is retained here because the
  current resolver/source-catalog node is "Filippo Sorcinelli - SAUF".
  This is a hierarchy classification only, not a canonical rename.

No changes to resolver tables, entity_market scoring, brand rollup logic,
URLs, or any existing brand_tier data.
"""

from alembic import op
import sqlalchemy as sa


revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Seed rows — KB-CAT1-A locked taxonomy
# (brand_name_normalized, node_type, parent_brand_normalized, notes)
# ---------------------------------------------------------------------------

_HIERARCHY_SEED = [
    (
        "xerjoff - join the club",
        "collection",
        "xerjoff",
        "Themed collection under parent brand Xerjoff. No independent market identity.",
    ),
    (
        "xerjoff - casamorati",
        "sub_brand",
        "xerjoff",
        "Historic acquisition (Casamorati, 1888 Italian house). Distinct aesthetics "
        "and loyal customer base; marketed separately.",
    ),
    (
        "xerjoff - xj oud attars",
        "collection",
        "xerjoff",
        "Themed oud attars/oils collection under Xerjoff. Not tracked in entity_market.",
    ),
    (
        "filippo sorcinelli - sauf",
        "collection",
        "filippo sorcinelli",
        "SAUF is the resolver/Fragrantica node name. Official navigation uses "
        "'Extrait de Musique' for this family. This is a hierarchy classification "
        "only — do not rename the resolver node.",
    ),
]


def upgrade() -> None:
    # Add node_type with CHECK constraint and default
    op.add_column(
        "brand_profiles",
        sa.Column(
            "node_type",
            sa.String(32),
            nullable=False,
            server_default="brand",
        ),
    )
    op.create_check_constraint(
        "ck_brand_profiles_node_type",
        "brand_profiles",
        "node_type IN ('brand', 'collection', 'sub_brand')",
    )

    # Add parent_brand_normalized — TEXT NULL, no FK
    op.add_column(
        "brand_profiles",
        sa.Column("parent_brand_normalized", sa.Text(), nullable=True),
    )

    # Seed the 4 confirmed hierarchy candidates.
    # If the parent row doesn't exist yet (e.g. Xerjoff might not have been
    # seeded in migration 044), insert it first with brand_tier='niche' so
    # the hierarchy seed can safely reference it. ON CONFLICT DO NOTHING
    # means existing rows are untouched.
    conn = op.get_bind()

    # Ensure parent brands exist (Xerjoff and Filippo Sorcinelli are already
    # in brand_profiles from migration 044/niche seed, but guard defensively)
    parent_rows = [
        ("xerjoff", "niche"),
        ("filippo sorcinelli", "niche"),
    ]
    for norm, tier in parent_rows:
        conn.execute(
            sa.text(
                "INSERT INTO brand_profiles (brand_name_normalized, brand_tier) "
                "VALUES (:n, :t) "
                "ON CONFLICT (brand_name_normalized) DO NOTHING"
            ),
            {"n": norm, "t": tier},
        )

    # Upsert hierarchy rows — insert if absent, update node_type +
    # parent_brand_normalized if the row already exists (it shouldn't unless
    # migration was run twice or the brand appeared in an earlier tier seed).
    for norm, node_type, parent, notes in _HIERARCHY_SEED:
        conn.execute(
            sa.text(
                "INSERT INTO brand_profiles "
                "  (brand_name_normalized, brand_tier, node_type, parent_brand_normalized, notes) "
                "VALUES (:n, 'niche', :nt, :p, :notes) "
                "ON CONFLICT (brand_name_normalized) DO UPDATE "
                "  SET node_type = EXCLUDED.node_type, "
                "      parent_brand_normalized = EXCLUDED.parent_brand_normalized, "
                "      notes = COALESCE(brand_profiles.notes, EXCLUDED.notes)"
            ),
            {"n": norm, "nt": node_type, "p": parent, "notes": notes},
        )


def downgrade() -> None:
    op.drop_constraint("ck_brand_profiles_node_type", "brand_profiles", type_="check")
    op.drop_column("brand_profiles", "parent_brand_normalized")
    op.drop_column("brand_profiles", "node_type")
