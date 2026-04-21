from __future__ import annotations

"""Candidate store — saves unresolved mention phrases to fragrance_candidates.

Design:
  - upsert on normalized_text (unique key)
  - on conflict: increment occurrences + update last_seen
  - batch_upsert_candidates() collects all phrases from a resolved_items list
    and issues ONE upsert per unique normalized_text, minimising round-trips

Usage::

    from perfume_trend_sdk.storage.entities.candidate_store import batch_upsert_candidates

    with session_scope() as db:
        batch_upsert_candidates(db, resolved_items, source_platform="youtube")
"""

import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import List

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Normalisation (mirrors resolver pre-normalisation rules)
# ---------------------------------------------------------------------------

def _normalize(raw: str) -> str:
    """Lowercase, strip, collapse spaces, remove punctuation."""
    s = raw.strip().lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^\w\s-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def batch_upsert_candidates(
    db: Session,
    resolved_items: List[dict],
    source_platform: str = "unknown",
) -> int:
    """Extract unresolved mentions from resolved_items and upsert to fragrance_candidates.

    Returns the number of candidate phrases processed.

    Strategy:
      1. Collect all unresolved_mentions across all resolved items.
      2. Aggregate by normalized_text in-memory — count occurrences + pick first raw_text.
      3. One SQL upsert per unique normalized_text.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Aggregate in-memory first
    aggregated: dict[str, dict] = {}
    for item in resolved_items:
        for raw_phrase in item.get("unresolved_mentions", []):
            if not raw_phrase or not raw_phrase.strip():
                continue
            norm = _normalize(raw_phrase)
            if not norm or len(norm) <= 3:
                continue  # too short to be meaningful
            if norm in aggregated:
                aggregated[norm]["count"] += 1
            else:
                aggregated[norm] = {"raw": raw_phrase.strip(), "count": 1}

    if not aggregated:
        return 0

    # Upsert each unique normalized phrase
    for normalized_text, meta in aggregated.items():
        _upsert_one(
            db=db,
            raw_text=meta["raw"],
            normalized_text=normalized_text,
            source_platform=source_platform,
            delta=meta["count"],
            now=now,
        )

    return len(aggregated)


def _upsert_one(
    db: Session,
    raw_text: str,
    normalized_text: str,
    source_platform: str,
    delta: int,
    now: str,
) -> None:
    """Insert new candidate or increment occurrences + update last_seen."""
    dialect = db.bind.dialect.name if db.bind else "unknown"

    if dialect == "postgresql":
        db.execute(
            text(
                "INSERT INTO fragrance_candidates "
                "(raw_text, normalized_text, source_platform, occurrences, first_seen, last_seen, confidence_score, status) "
                "VALUES (:raw, :norm, :src, :delta, :now, :now, 0.0, 'new') "
                "ON CONFLICT (normalized_text) DO UPDATE SET "
                "  occurrences = fragrance_candidates.occurrences + :delta, "
                "  last_seen = :now"
            ),
            {
                "raw": raw_text,
                "norm": normalized_text,
                "src": source_platform,
                "delta": delta,
                "now": now,
            },
        )
    else:
        # SQLite — INSERT OR IGNORE then UPDATE
        db.execute(
            text(
                "INSERT OR IGNORE INTO fragrance_candidates "
                "(raw_text, normalized_text, source_platform, occurrences, first_seen, last_seen, confidence_score, status) "
                "VALUES (:raw, :norm, :src, :delta, :now, :now, 0.0, 'new')"
            ),
            {
                "raw": raw_text,
                "norm": normalized_text,
                "src": source_platform,
                "delta": delta,
                "now": now,
            },
        )
        db.execute(
            text(
                "UPDATE fragrance_candidates SET "
                "  occurrences = occurrences + :delta, "
                "  last_seen = :now "
                "WHERE normalized_text = :norm"
            ),
            {"delta": delta, "now": now, "norm": normalized_text},
        )
