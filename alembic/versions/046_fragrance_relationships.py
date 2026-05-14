"""FTG-2 / RI1 — Relationship Intelligence Core

Revision ID: 046
Revises: 045
Create Date: 2026-05-14

Creates the Relationship Intelligence data foundation:
  fragrance_relationships  — curated relationships between fragrances
  relationship_evidence    — evidence records supporting each relationship

Design decisions (see fragrance_relationship.py docstring for full rationale):

  subject_canonical_name / object_canonical_name — TEXT (not UUID FK)
    Allows seeding untracked entities (Montblanc Explorer, Zara Red Temptation,
    Ariana Grande Cloud have no entity_market row at seed time).
    Joins to entity_market: JOIN entity_market em ON em.canonical_name = fr.subject_canonical_name

  relation_type — no CHECK constraint (mirrors brand_tier in migration 044).
    Application layer enforces VALID_RELATION_TYPES.

  is_public — FALSE for all seeded rows.
    FTG-3 / RI1-QA owns the operator review + public promotion gate.

  No public API or entity page behavior changed in this migration.

Seed: 7 operator-curated relationship rows + 7 dupe_map_seed evidence rows.

Relation type mapping vs legacy _DUPE_RAW:
  dupe_alternative     → dupe_of             (strong community clone consensus)
  designer_alternative → market_alternative_to (different house tier, same demand space)
  celebrity_alternative → market_alternative_to (celebrity brand, positioned near original)

Khamrah correction (founder 2026-05-14):
  Lattafa Khamrah → market_alternative_to → Kilian Angels' Share
  (not dupe_of — community signal is mixed on direct clone status)

Qahwa decision (FTG-2 engineering judgment):
  Lattafa Khamrah Qahwa → market_alternative_to → Kilian Angels' Share
  (conservative — same reasoning as parent Khamrah)

Alias collapse:
  "Club de Nuit Intense Man", "CDNIM", "Armaf CDNIM" are resolver aliases
  for "Armaf Club de Nuit Intense Man" — not separate relationships in RI1.
  RI1 stores canonical perfume identity; the resolver handles alias lookup.
"""

from __future__ import annotations

import uuid
from datetime import date

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None

_SEED_DATE = date(2026, 5, 14)

# Pre-generated UUIDs for seed rows (stable across runs, referenced by evidence rows)
_REL_IDS = {
    "cdnim": uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890"),
    "cdni": uuid.UUID("b2c3d4e5-f6a7-8901-bcde-f12345678901"),
    "montblanc_explorer": uuid.UUID("c3d4e5f6-a7b8-9012-cdef-012345678902"),
    "khamrah": uuid.UUID("d4e5f6a7-b8c9-0123-defa-123456789003"),
    "khamrah_qahwa": uuid.UUID("e5f6a7b8-c9d0-1234-efab-234567890104"),
    "zara_red_temptation": uuid.UUID("f6a7b8c9-d0e1-2345-fabc-345678901205"),
    "ariana_cloud": uuid.UUID("a7b8c9d0-e1f2-3456-abcd-456789012306"),
}

_RELATIONSHIPS = [
    {
        "id": str(_REL_IDS["cdnim"]),
        "subject_canonical_name": "Armaf Club de Nuit Intense Man",
        "relation_type": "dupe_of",
        "object_canonical_name": "Creed Aventus",
        "confidence_score": "0.850",
        "is_public": False,
        "operator_reviewed": True,
        "first_observed_date": _SEED_DATE,
        "last_confirmed_date": _SEED_DATE,
        "evidence_summary": (
            "Community-wide consensus: direct clone of Creed Aventus; "
            "widely used as a budget substitute. Operator-curated from _DUPE_RAW seed."
        ),
        "formula_version": 1,
    },
    {
        "id": str(_REL_IDS["cdni"]),
        "subject_canonical_name": "Armaf Club de Nuit Intense",
        "relation_type": "dupe_of",
        "object_canonical_name": "Creed Aventus",
        "confidence_score": "0.850",
        "is_public": False,
        "operator_reviewed": True,
        "first_observed_date": _SEED_DATE,
        "last_confirmed_date": _SEED_DATE,
        "evidence_summary": (
            "Community-established clone of Creed Aventus; "
            "frequently recommended as affordable alternative. Operator-curated from _DUPE_RAW seed."
        ),
        "formula_version": 1,
    },
    {
        "id": str(_REL_IDS["montblanc_explorer"]),
        "subject_canonical_name": "Montblanc Explorer",
        "relation_type": "market_alternative_to",
        "object_canonical_name": "Creed Aventus",
        "confidence_score": "0.700",
        "is_public": False,
        "operator_reviewed": True,
        "first_observed_date": _SEED_DATE,
        "last_confirmed_date": _SEED_DATE,
        "evidence_summary": (
            "Designer house product frequently positioned alongside Creed Aventus "
            "in fragrance community comparisons. Operator-curated from _DUPE_RAW seed."
        ),
        "formula_version": 1,
    },
    {
        "id": str(_REL_IDS["khamrah"]),
        "subject_canonical_name": "Lattafa Khamrah",
        "relation_type": "market_alternative_to",
        "object_canonical_name": "Kilian Angels' Share",
        "confidence_score": "0.700",
        "is_public": False,
        "operator_reviewed": True,
        "first_observed_date": _SEED_DATE,
        "last_confirmed_date": _SEED_DATE,
        "evidence_summary": (
            "Consistently discussed alongside Angels' Share in community reviews; "
            "community signal is mixed on direct clone status — classified as market alternative "
            "per FTG-2 conservative policy (founder correction 2026-05-14)."
        ),
        "formula_version": 1,
    },
    {
        "id": str(_REL_IDS["khamrah_qahwa"]),
        "subject_canonical_name": "Lattafa Khamrah Qahwa",
        "relation_type": "market_alternative_to",
        "object_canonical_name": "Kilian Angels' Share",
        "confidence_score": "0.700",
        "is_public": False,
        "operator_reviewed": True,
        "first_observed_date": _SEED_DATE,
        "last_confirmed_date": _SEED_DATE,
        "evidence_summary": (
            "Variant of Khamrah line; positioned in Angels' Share market space. "
            "Community dupe signal for Qahwa is weaker than for Khamrah — classified "
            "conservatively as market alternative (FTG-2 engineering judgment 2026-05-14)."
        ),
        "formula_version": 1,
    },
    {
        "id": str(_REL_IDS["zara_red_temptation"]),
        "subject_canonical_name": "Zara Red Temptation",
        "relation_type": "dupe_of",
        "object_canonical_name": "Maison Francis Kurkdjian Baccarat Rouge 540",
        "confidence_score": "0.850",
        "is_public": False,
        "operator_reviewed": True,
        "first_observed_date": _SEED_DATE,
        "last_confirmed_date": _SEED_DATE,
        "evidence_summary": (
            "Well-established community consensus: intentional clone of Baccarat Rouge 540 "
            "at mass-market price point. Operator-curated from _DUPE_RAW seed."
        ),
        "formula_version": 1,
    },
    {
        "id": str(_REL_IDS["ariana_cloud"]),
        "subject_canonical_name": "Ariana Grande Cloud",
        "relation_type": "market_alternative_to",
        "object_canonical_name": "Maison Francis Kurkdjian Baccarat Rouge 540",
        "confidence_score": "0.700",
        "is_public": False,
        "operator_reviewed": True,
        "first_observed_date": _SEED_DATE,
        "last_confirmed_date": _SEED_DATE,
        "evidence_summary": (
            "Celebrity fragrance positioned in BR540 market space; community notes "
            "similarity but not direct clone status. Operator-curated from _DUPE_RAW seed."
        ),
        "formula_version": 1,
    },
]

_EVIDENCE = [
    {
        "id": str(uuid.uuid4()),
        "relationship_id": str(_REL_IDS["cdnim"]),
        "evidence_type": "dupe_map_seed",
        "note": "Migrated from _DUPE_RAW: 'Armaf Club de Nuit Intense Man' → dupe_alternative",
        "observed_date": _SEED_DATE,
    },
    {
        "id": str(uuid.uuid4()),
        "relationship_id": str(_REL_IDS["cdni"]),
        "evidence_type": "dupe_map_seed",
        "note": "Migrated from _DUPE_RAW: 'Armaf Club de Nuit Intense' → dupe_alternative",
        "observed_date": _SEED_DATE,
    },
    {
        "id": str(uuid.uuid4()),
        "relationship_id": str(_REL_IDS["montblanc_explorer"]),
        "evidence_type": "dupe_map_seed",
        "note": "Migrated from _DUPE_RAW: 'Montblanc Explorer' → designer_alternative → market_alternative_to",
        "observed_date": _SEED_DATE,
    },
    {
        "id": str(uuid.uuid4()),
        "relationship_id": str(_REL_IDS["khamrah"]),
        "evidence_type": "dupe_map_seed",
        "note": (
            "Migrated from _DUPE_RAW: 'Lattafa Khamrah' → dupe_alternative → "
            "market_alternative_to (founder correction: mixed community signal on clone status)"
        ),
        "observed_date": _SEED_DATE,
    },
    {
        "id": str(uuid.uuid4()),
        "relationship_id": str(_REL_IDS["khamrah_qahwa"]),
        "evidence_type": "dupe_map_seed",
        "note": (
            "Migrated from _DUPE_RAW: 'Lattafa Khamrah Qahwa' → dupe_alternative → "
            "market_alternative_to (conservative: weaker independent clone signal than Khamrah)"
        ),
        "observed_date": _SEED_DATE,
    },
    {
        "id": str(uuid.uuid4()),
        "relationship_id": str(_REL_IDS["zara_red_temptation"]),
        "evidence_type": "dupe_map_seed",
        "note": "Migrated from _DUPE_RAW: 'Zara Red Temptation' → dupe_alternative",
        "observed_date": _SEED_DATE,
    },
    {
        "id": str(uuid.uuid4()),
        "relationship_id": str(_REL_IDS["ariana_cloud"]),
        "evidence_type": "dupe_map_seed",
        "note": (
            "Migrated from _DUPE_RAW: 'Ariana Grande Cloud' → celebrity_alternative → "
            "market_alternative_to"
        ),
        "observed_date": _SEED_DATE,
    },
]


def upgrade() -> None:
    # ── fragrance_relationships ──────────────────────────────────────────────
    op.create_table(
        "fragrance_relationships",
        sa.Column("id", PG_UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"),
                  nullable=False, primary_key=True),
        sa.Column("subject_canonical_name", sa.Text(), nullable=False),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("object_canonical_name", sa.Text(), nullable=False),
        sa.Column("confidence_score", sa.Numeric(4, 3), nullable=False,
                  server_default=sa.text("0.500")),
        sa.Column("is_public", sa.Boolean(), nullable=False,
                  server_default=sa.text("FALSE")),
        sa.Column("operator_reviewed", sa.Boolean(), nullable=False,
                  server_default=sa.text("FALSE")),
        sa.Column("first_observed_date", sa.Date(), nullable=False),
        sa.Column("last_confirmed_date", sa.Date(), nullable=False),
        sa.Column("evidence_summary", sa.Text(), nullable=True),
        sa.Column("formula_version", sa.Integer(), nullable=False,
                  server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "subject_canonical_name", "relation_type", "object_canonical_name",
            name="uq_fragrance_relationships_triple",
        ),
    )
    op.create_index(
        "ix_fragrance_relationships_subject",
        "fragrance_relationships",
        ["subject_canonical_name", "relation_type"],
    )
    op.create_index(
        "ix_fragrance_relationships_object",
        "fragrance_relationships",
        ["object_canonical_name", "relation_type"],
    )

    # ── relationship_evidence ────────────────────────────────────────────────
    op.create_table(
        "relationship_evidence",
        sa.Column("id", PG_UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"),
                  nullable=False, primary_key=True),
        sa.Column("relationship_id", PG_UUID(as_uuid=True),
                  sa.ForeignKey("fragrance_relationships.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("evidence_type", sa.String(32), nullable=False),
        sa.Column("content_item_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("query_text", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("observed_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_relationship_evidence_relationship_id",
        "relationship_evidence",
        ["relationship_id"],
    )

    # ── Seed relationships ───────────────────────────────────────────────────
    conn = op.get_bind()
    if _RELATIONSHIPS:
        conn.execute(
            sa.text(
                "INSERT INTO fragrance_relationships "
                "(id, subject_canonical_name, relation_type, object_canonical_name, "
                " confidence_score, is_public, operator_reviewed, "
                " first_observed_date, last_confirmed_date, evidence_summary, formula_version) "
                "VALUES (:id, :subject_canonical_name, :relation_type, :object_canonical_name, "
                "        :confidence_score, :is_public, :operator_reviewed, "
                "        :first_observed_date, :last_confirmed_date, :evidence_summary, "
                "        :formula_version) "
                "ON CONFLICT (subject_canonical_name, relation_type, object_canonical_name) "
                "DO NOTHING"
            ),
            _RELATIONSHIPS,
        )

    # ── Seed evidence ────────────────────────────────────────────────────────
    if _EVIDENCE:
        conn.execute(
            sa.text(
                "INSERT INTO relationship_evidence "
                "(id, relationship_id, evidence_type, note, observed_date) "
                "VALUES (:id, :relationship_id, :evidence_type, :note, :observed_date) "
                "ON CONFLICT DO NOTHING"
            ),
            _EVIDENCE,
        )


def downgrade() -> None:
    op.drop_index("ix_relationship_evidence_relationship_id",
                  table_name="relationship_evidence")
    op.drop_table("relationship_evidence")
    op.drop_index("ix_fragrance_relationships_object",
                  table_name="fragrance_relationships")
    op.drop_index("ix_fragrance_relationships_subject",
                  table_name="fragrance_relationships")
    op.drop_table("fragrance_relationships")
