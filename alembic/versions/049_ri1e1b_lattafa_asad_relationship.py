"""FTG-4 / RI1-E1B — Curated Canonical Relationship Gap Fill: Lattafa Asad → Sauvage Elixir

Revision ID: 049
Revises: 048
Create Date: 2026-05-15

Adds one operator-curated dupe_of relationship + one dupe_map_seed evidence row.

Subject: Lattafa Asad
Object:  Sauvage Elixir  (Dior; entity_market canonical_name confirmed production 2026-05-15)

Note on object canonical name:
  Fragrantica and entity_market both record this as "Sauvage Elixir" (brand="Dior") —
  NOT "Dior Sauvage Elixir". This matches the broader aggregation convention for
  Dior flankers: "Dior Sauvage" (entity_market) but "Sauvage Elixir" (separate
  Elixir concentration, stored without brand prefix). The TEXT column in
  fragrance_relationships stores whatever string entity_market.canonical_name holds;
  public display resolves the brand via the resolver.

Relation type rationale (dupe_of at 0.850):
  Lattafa Asad has stronger direct-clone consensus in the fragrance community than
  Khamrah → Angels' Share. "Asad" is Arabic for "lion" — the scent was explicitly
  marketed and widely discussed as a Sauvage Elixir clone from launch. YouTube and
  Reddit fragrance communities reference it as a budget/accessible Sauvage Elixir
  substitute with minimal hedging. The 0.850 confidence matches CDNIM → Aventus and
  Zara Red Temptation → Baccarat Rouge 540, both strong community dupe_of seeds.

is_public + operator_reviewed = TRUE:
  This is an operator-curated canonical gap fill, not a machine-generated candidate.
  Follows the FTG-3 promotion standard (all three gates satisfied: is_public, operator_reviewed,
  confidence ≥ 0.700). No separate promotion migration needed.

No schema changes. Data-only migration.
"""

from __future__ import annotations

import uuid
from datetime import date

from alembic import op

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None

_SEED_DATE = date(2026, 5, 15)

# Stable pre-generated UUIDs
_REL_ID = uuid.UUID("b8c9d0e1-f2a3-4567-bcde-567890123407")
_EV_ID = uuid.UUID("c9d0e1f2-a3b4-5678-cdef-678901234508")


def upgrade() -> None:
    conn = op.get_bind()

    # Relationship row
    conn.execute(
        __import__("sqlalchemy").text(
            """
            INSERT INTO fragrance_relationships (
                id,
                subject_canonical_name,
                relation_type,
                object_canonical_name,
                confidence_score,
                is_public,
                operator_reviewed,
                first_observed_date,
                last_confirmed_date,
                evidence_summary,
                formula_version,
                created_at
            ) VALUES (
                :id,
                :subject,
                :rtype,
                :object,
                :conf,
                :is_public,
                :op_reviewed,
                :first_obs,
                :last_conf,
                :ev_summary,
                1,
                NOW()
            )
            ON CONFLICT (subject_canonical_name, relation_type, object_canonical_name)
            DO NOTHING
            """
        ),
        {
            "id": str(_REL_ID),
            "subject": "Lattafa Asad",
            "rtype": "dupe_of",
            "object": "Sauvage Elixir",
            "conf": "0.850",
            "is_public": True,
            "op_reviewed": True,
            "first_obs": _SEED_DATE,
            "last_conf": _SEED_DATE,
            "ev_summary": (
                "Community-wide consensus: direct clone of Dior Sauvage Elixir; "
                "marketed and discussed as an accessible Sauvage Elixir substitute from launch. "
                "Operator-curated canonical gap fill (RI1-E1B, 2026-05-15)."
            ),
        },
    )

    # Evidence row
    conn.execute(
        __import__("sqlalchemy").text(
            """
            INSERT INTO relationship_evidence (
                id,
                relationship_id,
                evidence_type,
                note,
                observed_date,
                created_at
            ) VALUES (
                :id,
                :rel_id,
                'dupe_map_seed',
                :note,
                :obs_date,
                NOW()
            )
            ON CONFLICT DO NOTHING
            """
        ),
        {
            "id": str(_EV_ID),
            "rel_id": str(_REL_ID),
            "note": (
                "Operator-curated canonical gap fill: Lattafa Asad → dupe_of → Sauvage Elixir. "
                "Community fragrance discussion consistently identifies Asad as a direct "
                "Sauvage Elixir clone. Added RI1-E1B 2026-05-15."
            ),
            "obs_date": _SEED_DATE,
        },
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        __import__("sqlalchemy").text(
            "DELETE FROM fragrance_relationships WHERE id = :id"
        ),
        {"id": str(_REL_ID)},
    )
    # relationship_evidence rows cascade-deleted via ON DELETE CASCADE FK
