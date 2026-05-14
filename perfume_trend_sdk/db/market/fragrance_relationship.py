"""FTG-2 / RI1 — Relationship Intelligence Core.

Provides:
  FragranceRelationship — SQLAlchemy model for the fragrance_relationships table
  RelationshipEvidence  — SQLAlchemy model for the relationship_evidence table
  VALID_RELATION_TYPES  — frozenset of approved relation_type strings
  RELATIONSHIP_SEED     — canonical curated seed data (imported by migration + tests)
  get_relationships(db, subject_canonical_name, ...) -> list[FragranceRelationship]

Architecture layer:
  This module sits in the Encyclopedia / Canonical Classification layer (FTG-1/2).
  It must NOT import from the analysis layer (no circular dependencies).

Design decisions (finalized FTG-2 design lock):

  subject_canonical_name / object_canonical_name — TEXT, not UUID FK.
    Rationale: several seeded perfumes (Montblanc Explorer, Zara Red Temptation,
    Ariana Grande Cloud) have no entity_market row at seed time.  A UUID FK would
    block seeding.  TEXT stores the same string as entity_market.canonical_name
    for tracked entities; future joins: JOIN entity_market em ON
    em.canonical_name = fr.subject_canonical_name.  The "_name" suffix makes
    clear this is the canonical name string, not a surrogate PK.

  relation_type — no DB CHECK constraint (mirrors brand_tier design decision).
    Application layer enforces valid values via VALID_RELATION_TYPES.

  is_public = FALSE for all seeded rows.
    FTG-3 / RI1-QA owns the operator review + public promotion gate.
    FTG-2 does NOT change public entity page rendering.

  operator_reviewed = TRUE for all seeded rows.
    Seeded from founder-curated _DUPE_RAW data with manual review.

  consensus_status — deferred to FTG-3 / FTG-4.
    All seed rows would be 'strong', which carries no signal in v1.
    Add when auto-generated candidates with genuinely varied evidence arrive.

Relation type taxonomy (4 approved types):
  dupe_of              — direct clone; community consensus it is a deliberate copy
  market_alternative_to — commonly discussed as accessible alternative; may differ
                          structurally but occupies same demand space
  inspired_by           — stylistically in the direction of the original; lighter claim
  commonly_compared_to  — high comparison query volume; no explicit clone claim
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from perfume_trend_sdk.db.market.base import Base


# ---------------------------------------------------------------------------
# Approved relation type vocabulary
# ---------------------------------------------------------------------------

VALID_RELATION_TYPES: frozenset[str] = frozenset({
    "dupe_of",
    "market_alternative_to",
    "inspired_by",
    "commonly_compared_to",
})


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------

class FragranceRelationship(Base):
    """A curated relationship between two fragrances.

    subject_canonical_name — the alternative/clone (e.g. "Armaf Club de Nuit Intense Man")
    object_canonical_name  — the original/reference (e.g. "Creed Aventus")
    relation_type          — one of VALID_RELATION_TYPES
    confidence_score       — operator-assigned 0.000–1.000; seed defaults: dupe_of=0.85,
                             market_alternative_to=0.70
    is_public              — FALSE until FTG-3 operator review promotes it
    operator_reviewed      — TRUE for all FTG-2 seeded rows (founder-curated)
    first_observed_date    — date this relationship was first documented
    last_confirmed_date    — date last reconfirmed (same as first for seeded rows)
    evidence_summary       — optional plain-text rationale
    formula_version        — versioning per DATA0 policy; default 1
    """

    __tablename__ = "fragrance_relationships"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    subject_canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), nullable=False, default=Decimal("0.500")
    )
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    operator_reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    first_observed_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_confirmed_date: Mapped[date] = mapped_column(Date, nullable=False)
    evidence_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    formula_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    evidence: Mapped[list["RelationshipEvidence"]] = relationship(
        "RelationshipEvidence",
        back_populates="relationship",
        cascade="all, delete-orphan",
        lazy="select",
    )


class RelationshipEvidence(Base):
    """A single piece of evidence supporting a FragranceRelationship.

    evidence_type — 'dupe_map_seed' | 'content_item' | 'query_pattern' | 'operator_note'
    content_item_id — FK to canonical_content_items (nullable; used for content_item evidence)
    query_text  — raw query pattern observed (used for query_pattern evidence)
    note        — free-text annotation (used for operator_note / dupe_map_seed)
    """

    __tablename__ = "relationship_evidence"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    relationship_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fragrance_relationships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    query_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    observed_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    relationship: Mapped["FragranceRelationship"] = relationship(
        "FragranceRelationship", back_populates="evidence"
    )


# ---------------------------------------------------------------------------
# Canonical seed data (FTG-2 initial operator-curated set)
#
# Derived from _DUPE_RAW in entity_role.py but with semantically rigorous
# relation_type assignments (the dupe map legacy labels are preserved in
# entity_role.py for the existing UI until FTG-3 promotes RI1 data).
#
# Collapsing rules:
#   CDNIM / "Club de Nuit Intense Man" / "Armaf CDNIM" are resolver aliases
#   for "Armaf Club de Nuit Intense Man" — NOT separate relationships.
#   RI1 stores canonical perfume identity, not resolver aliases.
#
# Khamrah correction (founder 2026-05-14):
#   Khamrah is market_alternative_to (not dupe_of) — community signal is mixed
#   on direct clone status; Truth Graph classifies conservatively.
#
# Qahwa decision (FTG-2 engineering judgment):
#   Khamrah Qahwa is market_alternative_to (same reasoning as Khamrah parent;
#   its Angels' Share connection derives from brand family identity, not
#   independent dupe consensus — conservative classification preserved).
# ---------------------------------------------------------------------------

SEED_DATE = date(2026, 5, 14)

RELATIONSHIP_SEED: list[dict] = [
    {
        "subject_canonical_name": "Armaf Club de Nuit Intense Man",
        "relation_type": "dupe_of",
        "object_canonical_name": "Creed Aventus",
        "confidence_score": "0.850",
        "evidence_summary": (
            "Community-wide consensus: direct clone of Creed Aventus; "
            "widely used as a budget substitute. Operator-curated from _DUPE_RAW seed."
        ),
    },
    {
        "subject_canonical_name": "Armaf Club de Nuit Intense",
        "relation_type": "dupe_of",
        "object_canonical_name": "Creed Aventus",
        "confidence_score": "0.850",
        "evidence_summary": (
            "Community-established clone of Creed Aventus; "
            "frequently recommended as affordable alternative. Operator-curated from _DUPE_RAW seed."
        ),
    },
    {
        "subject_canonical_name": "Montblanc Explorer",
        "relation_type": "market_alternative_to",
        "object_canonical_name": "Creed Aventus",
        "confidence_score": "0.700",
        "evidence_summary": (
            "Designer house product frequently positioned alongside Creed Aventus "
            "in fragrance community comparisons. Operator-curated from _DUPE_RAW seed."
        ),
    },
    {
        "subject_canonical_name": "Lattafa Khamrah",
        "relation_type": "market_alternative_to",
        "object_canonical_name": "Kilian Angels' Share",
        "confidence_score": "0.700",
        "evidence_summary": (
            "Consistently discussed alongside Angels' Share in community reviews; "
            "community signal is mixed on direct clone status — classified as market alternative "
            "per FTG-2 conservative policy (founder correction 2026-05-14)."
        ),
    },
    {
        "subject_canonical_name": "Lattafa Khamrah Qahwa",
        "relation_type": "market_alternative_to",
        "object_canonical_name": "Kilian Angels' Share",
        "confidence_score": "0.700",
        "evidence_summary": (
            "Variant of Khamrah line; positioned in Angels' Share market space. "
            "Community dupe signal for Qahwa is weaker than for Khamrah — classified "
            "conservatively as market alternative (FTG-2 engineering judgment 2026-05-14)."
        ),
    },
    {
        "subject_canonical_name": "Zara Red Temptation",
        "relation_type": "dupe_of",
        "object_canonical_name": "Maison Francis Kurkdjian Baccarat Rouge 540",
        "confidence_score": "0.850",
        "evidence_summary": (
            "Well-established community consensus: intentional clone of Baccarat Rouge 540 "
            "at mass-market price point. Operator-curated from _DUPE_RAW seed."
        ),
    },
    {
        "subject_canonical_name": "Ariana Grande Cloud",
        "relation_type": "market_alternative_to",
        "object_canonical_name": "Maison Francis Kurkdjian Baccarat Rouge 540",
        "confidence_score": "0.700",
        "evidence_summary": (
            "Celebrity fragrance positioned in BR540 market space; community notes "
            "similarity but not direct clone status. Operator-curated from _DUPE_RAW seed."
        ),
    },
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_relationships(
    db: Session,
    subject_canonical_name: str,
    relation_type: str | None = None,
    public_only: bool = True,
) -> list[FragranceRelationship]:
    """Return relationships where subject is the given canonical name.

    Non-fatal: returns [] on any DB exception (table absent, connection error).

    Args:
        db:                     SQLAlchemy Session.
        subject_canonical_name: Canonical name of the subject (alternative/clone).
        relation_type:          Optional filter on relation_type.
        public_only:            When True (default), returns only is_public=TRUE rows.
                                Pass False to include all operator-reviewed rows
                                (e.g. admin/review tooling).

    Returns:
        List of FragranceRelationship rows, or [] on error.
    """
    try:
        query = sa.text(
            "SELECT id, subject_canonical_name, relation_type, object_canonical_name, "
            "       confidence_score, is_public, operator_reviewed, "
            "       first_observed_date, last_confirmed_date, evidence_summary, "
            "       formula_version, created_at "
            "FROM fragrance_relationships "
            "WHERE subject_canonical_name = :subject "
            + ("AND is_public = TRUE " if public_only else "")
            + ("AND relation_type = :rtype " if relation_type else "")
            + "ORDER BY confidence_score DESC"
        )
        params: dict = {"subject": subject_canonical_name}
        if relation_type:
            params["rtype"] = relation_type
        rows = db.execute(query, params).fetchall()
        # Return as lightweight namedtuple-compatible rows (not full ORM objects
        # to avoid lazy-load overhead in non-ORM sessions).
        return list(rows)
    except Exception:
        return []
