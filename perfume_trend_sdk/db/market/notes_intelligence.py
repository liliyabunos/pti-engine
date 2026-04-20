from __future__ import annotations

"""ORM models for the Notes & Brand Intelligence Layer (Phase 2).

Five tables built on top of the existing notes/accords/perfume_notes data:

  NoteCanonical      — semantic canonical note groups (bergamot, cedar, …)
  NoteCanonicalMap   — maps every note → its canonical note
  NoteStats          — precomputed per-canonical-note stats
  AccordStats        — precomputed per-accord stats
  NoteBrandStats     — note × brand relationship stats

All tables are read-only from the ingestion pipeline — populated exclusively
by the build_notes_intelligence job. Safe to truncate + rebuild at any time.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Float, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from perfume_trend_sdk.db.market.base import Base


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# notes_canonical
# ---------------------------------------------------------------------------

class NoteCanonical(Base):
    """Canonical note entity — the semantic root for a group of note variants.

    Examples:
      canonical_name="bergamot"  covers  bergamot, calabrian bergamot
      canonical_name="cedar"     covers  cedar, cedarwood, atlas cedar, virginian cedar
    """

    __tablename__ = "notes_canonical"
    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_notes_canonical_normalized"),
    )

    id: Mapped[str] = mapped_column(
        Text, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    note_family: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now_iso)


# ---------------------------------------------------------------------------
# note_canonical_map
# ---------------------------------------------------------------------------

class NoteCanonicalMap(Base):
    """One row per note in the notes table, pointing to its canonical group."""

    __tablename__ = "note_canonical_map"
    __table_args__ = (
        UniqueConstraint("note_id", name="uq_note_canonical_map_note_id"),
        Index("ix_note_canonical_map_canonical_id", "canonical_note_id"),
    )

    id: Mapped[str] = mapped_column(
        Text, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    note_id: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_note_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now_iso)


# ---------------------------------------------------------------------------
# note_stats
# ---------------------------------------------------------------------------

class NoteStats(Base):
    """Precomputed analytics per canonical note.

    Rebuilt in full by build_notes_intelligence.py — no partial updates.
    """

    __tablename__ = "note_stats"
    __table_args__ = (
        UniqueConstraint("canonical_note_id", name="uq_note_stats_canonical"),
    )

    id: Mapped[str] = mapped_column(
        Text, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    canonical_note_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    perfume_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    brand_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    top_position_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    middle_position_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    base_position_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unknown_position_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    computed_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now_iso)


# ---------------------------------------------------------------------------
# accord_stats
# ---------------------------------------------------------------------------

class AccordStats(Base):
    """Precomputed analytics per accord."""

    __tablename__ = "accord_stats"
    __table_args__ = (
        UniqueConstraint("accord_id", name="uq_accord_stats_accord"),
    )

    id: Mapped[str] = mapped_column(
        Text, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    accord_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    perfume_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    brand_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    computed_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now_iso)


# ---------------------------------------------------------------------------
# note_brand_stats
# ---------------------------------------------------------------------------

class NoteBrandStats(Base):
    """Note × brand relationship — how many perfumes from a brand carry a note."""

    __tablename__ = "note_brand_stats"
    __table_args__ = (
        UniqueConstraint(
            "canonical_note_id", "brand_id",
            name="uq_note_brand_stats_pair",
        ),
        Index("ix_note_brand_stats_note", "canonical_note_id"),
        Index("ix_note_brand_stats_brand", "brand_id"),
    )

    id: Mapped[str] = mapped_column(
        Text, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    canonical_note_id: Mapped[str] = mapped_column(Text, nullable=False)
    brand_id: Mapped[str] = mapped_column(Text, nullable=False)
    perfume_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    share: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    computed_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now_iso)
