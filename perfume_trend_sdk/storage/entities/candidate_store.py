from __future__ import annotations

"""Candidate store — saves unresolved mention phrases to fragrance_candidates.

Design:
  - upsert on normalized_text (unique key)
  - on conflict: increment occurrences + update last_seen
  - batch_upsert_candidates() collects all phrases from a resolved_items list,
    aggregates in-memory, then issues a SINGLE bulk upsert (Postgres) or
    per-row upserts (SQLite fallback).

Hot path: Postgres uses psycopg2 execute_values — one network round trip for
all phrases regardless of count.  Without this, N per-phrase roundtrips over
a remote proxy (Railway) degrade to O(N) × latency seconds.

Usage::

    from perfume_trend_sdk.storage.entities.candidate_store import batch_upsert_candidates

    with session_scope() as db:
        batch_upsert_candidates(db, resolved_items, source_platform="youtube")
"""

import logging
import os
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

    Returns the number of unique candidate phrases processed.

    Strategy:
      1. Collect all unresolved_mentions across all resolved items.
      2. Aggregate by normalized_text in-memory (count occurrences, keep first raw_text).
      3. Postgres: one bulk INSERT ... ON CONFLICT via psycopg2 execute_values (1 roundtrip).
         SQLite: per-row INSERT OR IGNORE + UPDATE (existing behaviour).
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

    dialect = db.bind.dialect.name if db.bind else "sqlite"

    if dialect == "postgresql":
        _bulk_upsert_postgres(aggregated, source_platform, now)
    else:
        for normalized_text, meta in aggregated.items():
            _upsert_one_sqlite(
                db=db,
                raw_text=meta["raw"],
                normalized_text=normalized_text,
                source_platform=source_platform,
                delta=meta["count"],
                now=now,
            )

    return len(aggregated)


def _bulk_upsert_postgres(
    aggregated: dict[str, dict],
    source_platform: str,
    now: str,
) -> None:
    """Single-roundtrip bulk upsert for Postgres using psycopg2 execute_values.

    Replaces N per-phrase DB roundtrips with one network call regardless of
    how many unique phrases were aggregated.
    """
    import psycopg2
    import psycopg2.extras

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("batch_upsert_candidates: DATABASE_URL not set for Postgres bulk upsert")

    sql = (
        "INSERT INTO fragrance_candidates "
        "(raw_text, normalized_text, source_platform, occurrences, first_seen, last_seen, confidence_score, status) "
        "VALUES %s "
        "ON CONFLICT (normalized_text) DO UPDATE SET "
        "  occurrences = fragrance_candidates.occurrences + EXCLUDED.occurrences, "
        "  last_seen = EXCLUDED.last_seen"
    )
    rows = [
        (meta["raw"], norm, source_platform, meta["count"], now, now, 0.0, "new")
        for norm, meta in aggregated.items()
    ]

    conn = psycopg2.connect(database_url)
    try:
        with conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, sql, rows, page_size=500)
    finally:
        conn.close()

    logger.debug("[candidates] bulk upserted %d phrases to fragrance_candidates", len(rows))


def _upsert_one_sqlite(
    db: Session,
    raw_text: str,
    normalized_text: str,
    source_platform: str,
    delta: int,
    now: str,
) -> None:
    """SQLite fallback: INSERT OR IGNORE then UPDATE."""
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
