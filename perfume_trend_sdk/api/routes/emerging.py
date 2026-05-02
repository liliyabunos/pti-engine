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

# Partial-name fragments that are substrings of tracked entity names and appear in
# the candidates queue due to resolver sliding-window n-gram extraction.
# These are NOT real emerging candidates — they are resolution artefacts.
# Do NOT add full multi-word phrases here (e.g. "creed silver mountain water" is legitimate).
_FRAGMENT_BLOCKLIST: frozenset[str] = frozenset({
    "de chanel",
    "bleu de",
    "de nuit",
    "de marly",
    "acqua di",
    "mountain water",
})


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
# v2 Schemas (emerging_signals table — channel-aware, title-first)
# ---------------------------------------------------------------------------

class EmergingSignalRow(BaseModel):
    id: int
    normalized_text: str
    display_name: str
    candidate_type: str
    total_mentions: int
    distinct_channels_count: int
    weighted_channel_score: float
    top_channel_title: Optional[str]
    top_channel_tier: Optional[str]
    first_seen: str
    last_seen: str
    days_active: int
    is_in_resolver: bool
    is_in_entity_market: bool
    emerging_score: float


class EmergingV2Response(BaseModel):
    candidates: List[EmergingSignalRow]
    total_in_table: int
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
  AND COALESCE(fc.distinct_sources_count, 1) >= :min_sources
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
    min_sources: int = Query(default=2, ge=1, description="Minimum distinct sources (use 1 for analyst/debug mode)"),
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
                    "min_sources": min_sources,
                    "days": days,
                    "entity_type": entity_type,
                },
            )

        # Build optional entity_type clause
        entity_type_clause = ""
        params: dict = {
            "min_mentions": min_mentions,
            "min_sources": min_sources,
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

            # Python-side fragment blocklist — suppress resolution artefacts
            if (norm_text or "") in _FRAGMENT_BLOCKLIST:
                continue

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
                "min_sources": min_sources,
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
                "min_sources": min_sources,
                "days": days,
                "entity_type": entity_type,
            },
        )


# ---------------------------------------------------------------------------
# v2 — channel-aware, title-first emerging signals
# ---------------------------------------------------------------------------

_V2_TABLE_CHECK = """
SELECT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'emerging_signals'
)
"""

_V2_CANDIDATES_SQL = """
SELECT
    es.id,
    es.normalized_text,
    es.display_name,
    es.candidate_type,
    es.total_mentions,
    es.distinct_channels_count,
    es.weighted_channel_score,
    es.top_channel_title,
    es.top_channel_tier,
    es.first_seen,
    es.last_seen,
    es.days_active,
    es.is_in_resolver,
    es.is_in_entity_market,
    es.emerging_score
FROM emerging_signals es
WHERE es.review_status != 'rejected'
  AND es.is_in_resolver = FALSE
  AND es.is_in_entity_market = FALSE
  AND es.distinct_channels_count >= :min_channels
  AND es.weighted_channel_score >= :min_channel_score
  AND es.last_seen >= NOW() - CAST(:days || ' days' AS INTERVAL)
  {type_clause}
ORDER BY es.emerging_score DESC, LENGTH(es.normalized_text) DESC
LIMIT :fetch_limit
"""

_V2_TOTAL_SQL = """
SELECT COUNT(*) FROM emerging_signals
"""

# ---------------------------------------------------------------------------
# v2 response-layer noise filters (applied in Python, no DB writes)
# ---------------------------------------------------------------------------

# Tokens that, when they appear at the END of a candidate phrase, indicate the
# phrase is an incomplete sliding-window fragment cut off mid-title.
# e.g. "Marc Jacobs Daisy Wild Eau" → ends with "eau" → noise
_V2_WEAK_ENDINGS: frozenset[str] = frozenset({
    "eau", "with", "so", "and", "of", "the", "for", "review",
})

# Tokens that, when they appear at the START of a candidate phrase, indicate the
# phrase began mid-title (continuation of a longer phrase).
# e.g. "With You Intense" → starts with "with" → noise (subphrase of something longer)
_V2_WEAK_STARTS: frozenset[str] = frozenset({
    "eau", "with", "so", "and", "of", "the", "for",
})

# Explicit full-phrase blocklist for patterns not caught by weak-ending/starting
# guards (e.g. parallel overlapping windows that don't start/end on weak tokens).
_V2_NOISE_PHRASES: frozenset[str] = frozenset({
    "game of",
    "minute review",
    "full review",
    "honest review",
    "first impressions",
    "fragrance review",
    "perfume review",
    "top fragrances",
    "best fragrances",
    "wild eau so extra",        # parallel overlap: "marc jacobs daisy wild" vs "wild eau so extra"
    "daisy wild eau so",        # parallel overlap
    "jacobs daisy wild eau",    # parallel overlap
})


def _is_noise_phrase(text: str) -> bool:
    """Return True if *text* is a noise fragment that should be suppressed.

    Three checks (in order):
    1. Exact match in _V2_NOISE_PHRASES blocklist.
    2. Last token is in _V2_WEAK_ENDINGS → phrase is cut off at its right edge.
    3. First token is in _V2_WEAK_STARTS → phrase is cut off at its left edge.
    """
    if text in _V2_NOISE_PHRASES:
        return True
    tokens = text.split()
    if not tokens:
        return False
    if tokens[-1] in _V2_WEAK_ENDINGS:
        return True
    if tokens[0] in _V2_WEAK_STARTS:
        return True
    return False


# ---------------------------------------------------------------------------
# Subphrase suppression helpers
# ---------------------------------------------------------------------------

def _is_subphrase(shorter: str, longer: str) -> bool:
    """Return True if *shorter* is a contiguous token-window of *longer*.

    "jean paul" is a subphrase of "jean paul gaultier" → True
    "paul gaultier" is a subphrase of "jean paul gaultier" → True
    "armani stronger" is a subphrase of "armani stronger with you" → True
    "khadlaj icon" is NOT a subphrase of "givenchy gentleman society" → False
    """
    s_tokens = shorter.split()
    l_tokens = longer.split()
    n = len(s_tokens)
    if n == 0 or n >= len(l_tokens):
        return False
    for i in range(len(l_tokens) - n + 1):
        if l_tokens[i : i + n] == s_tokens:
            return True
    return False


def _suppress_subphrases(candidates: List["EmergingSignalRow"]) -> List["EmergingSignalRow"]:
    """Remove candidates whose normalized_text is a contiguous token-window of any
    already-accepted candidate with equal or better emerging_score.

    Candidates are expected to be pre-sorted by (emerging_score DESC, len DESC) so
    longer phrases always appear before their shorter sub-phrases when scores tie.
    """
    accepted: List["EmergingSignalRow"] = []
    accepted_texts: List[str] = []

    for c in candidates:
        norm = c.normalized_text
        suppressed = any(_is_subphrase(norm, longer) for longer in accepted_texts)
        if not suppressed:
            accepted.append(c)
            accepted_texts.append(norm)

    return accepted


@router.get("/emerging/v2", response_model=EmergingV2Response, summary="Emerging signals v2 (channel-aware)")
def get_emerging_v2(
    limit: int = Query(default=25, ge=1, le=100),
    days: int = Query(default=14, ge=1, le=365),
    min_channels: int = Query(default=2, ge=1, description="Minimum distinct channels (use 1 for debug)"),
    min_channel_score: float = Query(default=0.0, ge=0.0, description="Minimum weighted channel score"),
    candidate_type: Optional[str] = Query(default=None, description="perfume | brand | clone_reference | flanker | unknown"),
    db: Session = Depends(get_db_session),
) -> EmergingV2Response:
    """
    Return channel-weighted emerging trend signals from emerging_signals table.

    Signals are sourced from channel_poll video titles (not descriptions) and
    ranked by weighted_channel_score × recency_factor.

    Populate the table by running:
      python3 -m perfume_trend_sdk.jobs.extract_emerging_signals --days 7

    Hidden from results:
      - Phrases already in resolver_aliases (is_in_resolver=TRUE)
      - Phrases already in entity_market (is_in_entity_market=TRUE)
      - Manually rejected entries (review_status='rejected')
    """
    filters: dict = {
        "limit": limit,
        "days": days,
        "min_channels": min_channels,
        "min_channel_score": min_channel_score,
        "candidate_type": candidate_type,
    }

    try:
        # Graceful fallback for SQLite dev or pre-migration environments
        result = db.execute(text(_V2_TABLE_CHECK))
        table_exists = result.scalar()
        if not table_exists:
            _log.debug("emerging_signals table not found — returning empty v2 list")
            return EmergingV2Response(
                candidates=[],
                total_in_table=0,
                as_of=date.today().isoformat(),
                filters_applied=filters,
            )

        type_clause = ""
        # Oversample to ensure subphrase suppression has enough candidates to fill
        # the requested limit after filtering.  Cap at 300 to bound query size.
        fetch_limit = min(limit * 6, 300)
        params: dict = {
            "days": days,
            "min_channels": min_channels,
            "min_channel_score": min_channel_score,
            "fetch_limit": fetch_limit,
        }
        if candidate_type:
            type_clause = "AND es.candidate_type = :candidate_type"
            params["candidate_type"] = candidate_type

        sql = _V2_CANDIDATES_SQL.format(type_clause=type_clause)
        rows = db.execute(text(sql), params).fetchall()

        total_in_table = db.execute(text(_V2_TOTAL_SQL)).scalar() or 0

        candidates: List[EmergingSignalRow] = []
        for row in rows:
            (
                row_id, norm_text, display_name, cand_type,
                total_mentions, distinct_channels, weighted_score,
                top_ch_title, top_ch_tier,
                first_seen_raw, last_seen_raw, days_active,
                is_resolver, is_market, emerging_score,
            ) = row

            candidates.append(EmergingSignalRow(
                id=row_id,
                normalized_text=norm_text or "",
                display_name=display_name or "",
                candidate_type=cand_type or "unknown",
                total_mentions=total_mentions or 0,
                distinct_channels_count=distinct_channels or 0,
                weighted_channel_score=round(float(weighted_score or 0), 4),
                top_channel_title=top_ch_title,
                top_channel_tier=top_ch_tier,
                first_seen=_safe_date_str(first_seen_raw),
                last_seen=_safe_date_str(last_seen_raw),
                days_active=max(int(days_active or 1), 1),
                is_in_resolver=bool(is_resolver),
                is_in_entity_market=bool(is_market),
                emerging_score=round(float(emerging_score or 0), 4),
            ))

        # E3-C: Remove noise fragments (weak-ending/starting, explicit blocklist)
        candidates = [c for c in candidates if not _is_noise_phrase(c.normalized_text)]

        # E3-B: Suppress sub-phrases — hide shorter phrases that are contiguous
        # token-windows of a higher-ranked (or equal-score, longer) phrase.
        candidates = _suppress_subphrases(candidates)[:limit]

        return EmergingV2Response(
            candidates=candidates,
            total_in_table=total_in_table,
            as_of=date.today().isoformat(),
            filters_applied=filters,
        )

    except Exception as exc:
        _log.warning("emerging/v2 endpoint error — %s", exc, exc_info=True)
        return EmergingV2Response(
            candidates=[],
            total_in_table=0,
            as_of=date.today().isoformat(),
            filters_applied=filters,
        )
