from __future__ import annotations

"""
Emerging Trend Candidates — read-only intelligence layer.

GET /api/v1/emerging
    Surface high-signal fragrance candidates from fragrance_candidates that appear
    in ingested content but are not yet resolved to any tracked entity_market row.
    No writes. No schema changes. No promotion workflow.

Exclusions:
  - Candidates already present as a resolver alias (resolver_aliases.normalized_alias_text)
  - Candidates already tracked in entity_market (LOWER(canonical_name) exact match)

SQLite / dev fallback:
  fragrance_candidates and resolver_aliases are Postgres-only tables.
  If they do not exist the endpoint returns an empty candidates list gracefully.
"""

import logging
import math
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from perfume_trend_sdk.api.dependencies import get_db_session

_log = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class EmergingCandidateRow(BaseModel):
    id: int
    display_name: str
    raw_name: str
    mention_count: int
    distinct_sources_count: int
    first_seen: str
    last_seen: str
    days_active: int
    # confidence_score is ln(occurrences+1); normalized to 0-1 as min(val/6.0, 1.0)
    confidence_score: Optional[float]
    confidence_normalized: float      # 0.0–1.0 for UI badge colouring
    emerging_score: float
    validation_status: str
    approved_entity_type: Optional[str]


class EmergingResponse(BaseModel):
    candidates: List[EmergingCandidateRow]
    total_in_queue: int
    as_of: str
    filters_applied: dict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAFE_TABLE_CHECK = """
SELECT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'fragrance_candidates'
)
"""

_CANDIDATES_SQL = """
SELECT
    fc.id,
    fc.normalized_text,
    fc.raw_text,
    fc.occurrences,
    fc.distinct_sources_count,
    fc.first_seen,
    fc.last_seen,
    fc.confidence_score,
    fc.validation_status,
    fc.candidate_type,
    fc.approved_entity_type,
    -- emerging_score = occurrences × recency_factor × normalized_confidence
    -- confidence_score = ln(occurrences+1); divide by 6.0 to normalize to ~0-1 range
    fc.occurrences
        * EXP(-0.1 * EXTRACT(EPOCH FROM (NOW() - fc.last_seen::timestamptz)) / 86400.0)
        * LEAST(fc.confidence_score / 6.0, 1.0)            AS emerging_score,
    EXTRACT(EPOCH FROM (
        fc.last_seen::timestamptz - fc.first_seen::timestamptz
    )) / 86400.0                                            AS span_days
FROM fragrance_candidates fc
WHERE fc.validation_status = 'accepted_rule_based'
  AND fc.review_status != 'rejected_final'
  AND fc.occurrences >= :min_mentions
  AND fc.last_seen::date >= CURRENT_DATE - CAST(:days || ' days' AS INTERVAL)
  -- Exclude candidates already present as resolver aliases (already known to KB)
  AND NOT EXISTS (
      SELECT 1 FROM resolver_aliases ra
      WHERE ra.normalized_alias_text = fc.normalized_text
  )
  -- Exclude candidates whose name exactly matches a tracked entity_market row
  AND NOT EXISTS (
      SELECT 1 FROM entity_market em
      WHERE LOWER(em.canonical_name) = fc.normalized_text
  )
  -- Exclude pure generic fragrance vocabulary (noise from content descriptions)
  AND fc.normalized_text !~* '\m(fragrance|cologne|perfume|parfum|scent)\M'
  {entity_type_clause}
ORDER BY emerging_score DESC
LIMIT :limit
"""

_TOTAL_SQL = """
SELECT COUNT(*)
FROM fragrance_candidates fc
WHERE fc.validation_status = 'accepted_rule_based'
  AND fc.review_status != 'rejected_final'
"""


def _title_case(text: str) -> str:
    """Title-case a normalized (lowercase) candidate text for display."""
    return " ".join(w.capitalize() for w in text.split())


def _safe_date_str(val) -> str:
    """Return ISO date string from various timestamp formats stored as text."""
    if val is None:
        return ""
    s = str(val)
    # Trim to date portion if full ISO timestamp
    return s[:10]


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/emerging", response_model=EmergingResponse, summary="Emerging trend candidates")
def get_emerging(
    limit: int = Query(default=25, ge=1, le=100),
    min_mentions: int = Query(default=3, ge=1, alias="min_mentions"),
    days: int = Query(default=14, ge=1, le=365),
    entity_type: Optional[str] = Query(default=None, description="perfume | brand | note"),
    db: Session = Depends(get_db_session),
) -> EmergingResponse:
    """
    Return emerging fragrance candidates ranked by recency-weighted mention score.

    Candidates are sourced from fragrance_candidates (accumulated by the ingestion
    pipeline) and filtered to exclude entities already resolved in entity_market or
    present as resolver aliases.
    """
    try:
        # Graceful fallback for SQLite dev environments
        result = db.execute(text(_SAFE_TABLE_CHECK))
        table_exists = result.scalar()
        if not table_exists:
            _log.debug("fragrance_candidates table not found — returning empty emerging list")
            return EmergingResponse(
                candidates=[],
                total_in_queue=0,
                as_of=date.today().isoformat(),
                filters_applied={
                    "limit": limit,
                    "min_mentions": min_mentions,
                    "days": days,
                    "entity_type": entity_type,
                },
            )

        # Build optional entity_type clause
        entity_type_clause = ""
        params: dict = {
            "min_mentions": min_mentions,
            "days": days,
            "limit": limit,
        }
        if entity_type and entity_type in ("perfume", "brand", "note"):
            entity_type_clause = "AND (fc.candidate_type = :entity_type OR fc.approved_entity_type = :entity_type)"
            params["entity_type"] = entity_type

        sql = _CANDIDATES_SQL.format(entity_type_clause=entity_type_clause)
        rows = db.execute(text(sql), params).fetchall()

        # Total in queue (unfiltered, for context)
        total_in_queue = db.execute(text(_TOTAL_SQL)).scalar() or 0

        candidates: List[EmergingCandidateRow] = []
        for row in rows:
            (
                cid, norm_text, raw_text, occurrences, distinct_sources,
                first_seen_raw, last_seen_raw, confidence_score,
                validation_status, candidate_type, approved_entity_type,
                emerging_score, span_days,
            ) = row

            conf_raw = float(confidence_score) if confidence_score is not None else None
            conf_norm = min(conf_raw / 6.0, 1.0) if conf_raw is not None else 0.5

            first_str = _safe_date_str(first_seen_raw)
            last_str = _safe_date_str(last_seen_raw)

            # days_active: span between first and last seen, minimum 1
            days_active = max(int(span_days) if span_days is not None else 0, 1)

            candidates.append(EmergingCandidateRow(
                id=cid,
                display_name=_title_case(norm_text or ""),
                raw_name=raw_text or norm_text or "",
                mention_count=occurrences or 0,
                distinct_sources_count=distinct_sources or 1,
                first_seen=first_str,
                last_seen=last_str,
                days_active=days_active,
                confidence_score=conf_raw,
                confidence_normalized=round(conf_norm, 3),
                emerging_score=round(float(emerging_score), 3) if emerging_score is not None else 0.0,
                validation_status=validation_status or "",
                approved_entity_type=approved_entity_type or candidate_type or None,
            ))

        return EmergingResponse(
            candidates=candidates,
            total_in_queue=total_in_queue,
            as_of=date.today().isoformat(),
            filters_applied={
                "limit": limit,
                "min_mentions": min_mentions,
                "days": days,
                "entity_type": entity_type,
            },
        )

    except Exception as exc:
        _log.warning("emerging endpoint error — %s", exc, exc_info=True)
        return EmergingResponse(
            candidates=[],
            total_in_queue=0,
            as_of=date.today().isoformat(),
            filters_applied={
                "limit": limit,
                "min_mentions": min_mentions,
                "days": days,
                "entity_type": entity_type,
            },
        )
