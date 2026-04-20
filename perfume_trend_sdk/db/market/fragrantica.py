from __future__ import annotations

"""SQLAlchemy ORM models for the Fragrantica enrichment layer.

Five tables:
  FragranticaRecord  — parsed Fragrantica page data per perfume
  Note               — canonical note library
  Accord             — canonical accord library
  PerfumeNote        — many-to-many: perfume ↔ note (with position)
  PerfumeAccord      — many-to-many: perfume ↔ accord

UUIDs are stored as str / Text for SQLite + Postgres compatibility,
matching the existing pattern in identity_map.py and migration 007.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from perfume_trend_sdk.db.market.base import Base


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# fragrantica_records
# ---------------------------------------------------------------------------

class FragranticaRecord(Base):
    """One row per successfully fetched + parsed Fragrantica page.

    fragrance_id  — resolver DB reference key (fragrance_master.fragrance_id)
    perfume_id    — market UUID (perfumes.id) — may be NULL if no identity map entry
    """

    __tablename__ = "fragrantica_records"
    __table_args__ = (
        UniqueConstraint("fragrance_id", name="uq_fragrantica_records_fragrance_id"),
        Index("ix_fragrantica_records_perfume_id", "perfume_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    fragrance_id: Mapped[str] = mapped_column(Text, nullable=False)
    perfume_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    raw_payload_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    brand_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    perfume_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    accords_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    notes_top_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    notes_middle_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    notes_base_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    rating_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rating_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    release_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    perfumer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    similar_perfumes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    fetched_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now_iso)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now_iso)


# ---------------------------------------------------------------------------
# notes
# ---------------------------------------------------------------------------

class Note(Base):
    """Canonical note entity (bergamot, rose, sandalwood, …)."""

    __tablename__ = "notes"
    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_notes_normalized_name"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now_iso)


# ---------------------------------------------------------------------------
# accords
# ---------------------------------------------------------------------------

class Accord(Base):
    """Canonical accord entity (floral, woody, fresh, …)."""

    __tablename__ = "accords"
    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_accords_normalized_name"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now_iso)


# ---------------------------------------------------------------------------
# perfume_notes  (many-to-many with position)
# ---------------------------------------------------------------------------

class PerfumeNote(Base):
    """Links a market perfume (UUID) to a note with its position (top/middle/base)."""

    __tablename__ = "perfume_notes"
    __table_args__ = (
        UniqueConstraint(
            "perfume_id", "note_id", "note_position",
            name="uq_perfume_notes_triplet",
        ),
        Index("ix_perfume_notes_perfume_id", "perfume_id"),
        Index("ix_perfume_notes_note_id", "note_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    perfume_id: Mapped[str] = mapped_column(String(36), nullable=False)
    note_id: Mapped[str] = mapped_column(String(36), nullable=False)
    note_position: Mapped[str] = mapped_column(Text, nullable=False, default="unknown")
    source: Mapped[str] = mapped_column(Text, nullable=False, default="fragrantica")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now_iso)


# ---------------------------------------------------------------------------
# perfume_accords  (many-to-many)
# ---------------------------------------------------------------------------

class PerfumeAccord(Base):
    """Links a market perfume (UUID) to an accord."""

    __tablename__ = "perfume_accords"
    __table_args__ = (
        UniqueConstraint(
            "perfume_id", "accord_id",
            name="uq_perfume_accords_pair",
        ),
        Index("ix_perfume_accords_perfume_id", "perfume_id"),
        Index("ix_perfume_accords_accord_id", "accord_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    perfume_id: Mapped[str] = mapped_column(String(36), nullable=False)
    accord_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="fragrantica")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now_iso)
