from __future__ import annotations

"""SQLAlchemy ORM model for the fragrance_candidates table (Phase 3).

Stores unresolved perfume/brand mention phrases from ingestion pipelines.
Unique on normalized_text — upserted on every unresolved mention occurrence.

Status lifecycle:
  new        — just inserted or incremented, not yet reviewed
  aggregated — occurrences were recomputed and confidence_score updated
  rejected   — ruled out (noise, generic phrase, etc.)
"""

import math
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Float, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from perfume_trend_sdk.db.market.base import Base


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FragranceCandidate(Base):
    """One row per unique unresolved mention phrase."""

    __tablename__ = "fragrance_candidates"
    __table_args__ = (
        UniqueConstraint("normalized_text", name="uq_fragrance_candidates_normalized_text"),
        Index("ix_fragrance_candidates_status", "status"),
        Index("ix_fragrance_candidates_occurrences", "occurrences"),
        Index("ix_fragrance_candidates_source_platform", "source_platform"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_platform: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen: Mapped[str] = mapped_column(Text, nullable=False, default=_now_iso)
    last_seen: Mapped[str] = mapped_column(Text, nullable=False, default=_now_iso)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="new")

    @staticmethod
    def compute_confidence(occurrences: int) -> float:
        """confidence_score = log(occurrences + 1), rounded to 4 decimal places."""
        return round(math.log(occurrences + 1), 4)
