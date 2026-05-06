from __future__ import annotations

"""
Entity routes — Market Terminal API v1.

GET /api/v1/entities                      — list all entities with latest snapshot
GET /api/v1/entities/perfume/{id}         — perfume entity detail (tracked + catalog-only)
GET /api/v1/entities/brand/{id}           — brand entity detail (tracked + catalog-only)
GET /api/v1/entities/{entity_id}          — generic entity detail (backward compat)
GET /api/v1/entities/{entity_id}/mentions — raw mention drilldown
"""

import json
import logging
import re
import uuid as _uuid_mod
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from perfume_trend_sdk.api.dependencies import get_db_session
from perfume_trend_sdk.api.queries import (
    fetch_brand_name_map,
    fetch_latest_rows,
    fetch_latest_signal_map,
    get_brand_name,
)
from perfume_trend_sdk.api.schemas.entity import (
    DriverRow,
    EntityDetail,
    EntitySummary,
    MentionRow,
    RecentMentionRow,
    SignalRow,
    SnapshotRow,
)
from perfume_trend_sdk.db.market.entity_mention import EntityMention
from perfume_trend_sdk.db.market.entity_timeseries_daily import EntityTimeSeriesDaily
from perfume_trend_sdk.db.market.models import EntityMarket
from perfume_trend_sdk.db.market.signal import Signal
from perfume_trend_sdk.analysis.topic_intelligence.entity_role import classify_entity_role

router = APIRouter()
_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_dt(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _get_entity_or_404(db: Session, entity_id: str) -> EntityMarket:
    obj = db.query(EntityMarket).filter_by(entity_id=entity_id).first()
    if obj is None:
        raise HTTPException(status_code=404, detail=f"Entity not found: {entity_id}")
    return obj


def _get_latest_snapshot(db: Session, entity_uuid) -> Optional[EntityTimeSeriesDaily]:
    return (
        db.query(EntityTimeSeriesDaily)
        .filter_by(entity_id=entity_uuid)
        .order_by(EntityTimeSeriesDaily.date.desc())
        .first()
    )


def _get_history(db: Session, entity_uuid, days: int) -> List[EntityTimeSeriesDaily]:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return (
        db.query(EntityTimeSeriesDaily)
        .filter(
            EntityTimeSeriesDaily.entity_id == entity_uuid,
            EntityTimeSeriesDaily.date >= cutoff,
        )
        .order_by(EntityTimeSeriesDaily.date.asc())
        .all()
    )


def _get_signals(db: Session, entity_uuid, limit: int) -> List[Signal]:
    return (
        db.query(Signal)
        .filter_by(entity_id=entity_uuid)
        .order_by(Signal.detected_at.desc())
        .limit(limit)
        .all()
    )


def _get_recent_mentions(db: Session, entity_uuid, limit: int = 5) -> List[dict]:
    """Return mentions enriched with source intelligence data (Phase I1)."""
    try:
        rows = db.execute(text("""
            SELECT
                em.source_platform,
                em.source_url,
                em.author_name,
                em.author_id,
                em.engagement,
                em.occurred_at,
                ms.views,
                ms.likes,
                ms.comments_count,
                ms.engagement_rate
            FROM entity_mentions em
            LEFT JOIN mention_sources ms ON ms.mention_id = em.id
            WHERE em.entity_id = :eid
            ORDER BY em.occurred_at DESC
            LIMIT :lim
        """), {"eid": str(entity_uuid), "lim": limit}).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception:
        # Fallback to ORM without source data (e.g. SQLite dev)
        rows_orm = (
            db.query(EntityMention)
            .filter_by(entity_id=entity_uuid)
            .order_by(EntityMention.occurred_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "source_platform": m.source_platform,
                "source_url": m.source_url,
                "author_name": m.author_name or m.author_id,
                "author_id": m.author_id,
                "engagement": m.engagement,
                "occurred_at": m.occurred_at,
                "views": None,
                "likes": None,
                "comments_count": None,
                "engagement_rate": None,
            }
            for m in rows_orm
        ]


def _get_entity_topics(
    db: Session,
    entity_id_str: str,
    limit_per_type: int = 8,
) -> tuple[list[str], list[str], list[str], list[str], list[str], list[str]]:
    """Phase I5/I7 — Return (top_topics, top_queries, top_subreddits, differentiators, positioning, intents).

    Aggregates entity_topic_links grouped by (topic_type, topic_text) ordered by
    occurrence count DESC, then avg source_score DESC.

    Phase I5 fields (raw):
      top_topics     — semantic topic labels (e.g. "compliment getter", "blind buy")
      top_queries    — YouTube search queries (e.g. "creed aventus review")
      top_subreddits — Reddit communities (e.g. "fragrance")

    Phase I7 semantic fields (classified):
      differentiators — uniqueness/value signals ("dupe / alternative", "compliment getter", …)
      positioning     — identity tags ("vanilla", "niche fragrance", "men's fragrance", …)
      intents         — search intent (queries + intent labels like "review", "gift idea", …)
    """
    from perfume_trend_sdk.analysis.topic_intelligence.semantic import classify_entity_topics
    try:
        rows = db.execute(text("""
            SELECT topic_type, topic_text,
                   COUNT(*) as occ,
                   COALESCE(AVG(source_score), 0) as avg_score
            FROM entity_topic_links
            WHERE entity_id = :eid
            GROUP BY topic_type, topic_text
            ORDER BY occ DESC, avg_score DESC
        """), {"eid": entity_id_str}).fetchall()
    except Exception as exc:
        _log.warning("[I5] entity_topics query failed: %s", exc)
        return [], [], [], [], [], []

    topics: list[str] = []
    queries: list[str] = []
    subreddits: list[str] = []
    for ttype, ttext, _occ, _score in rows:
        if ttype == "topic" and len(topics) < limit_per_type:
            topics.append(ttext)
        elif ttype == "query" and len(queries) < limit_per_type:
            queries.append(ttext)
        elif ttype == "subreddit" and len(subreddits) < limit_per_type:
            subreddits.append(ttext)

    # Phase I7 — semantic classification
    raw_for_classify = [(r[0], r[1], int(r[2]), float(r[3])) for r in rows]
    profile = classify_entity_topics(raw_for_classify)
    return topics, queries, subreddits, profile.differentiators, profile.positioning, profile.intents


def _get_brand_topics(
    db: Session,
    brand_name: str,
    limit_per_type: int = 8,
) -> tuple[list[str], list[str], list[str], list[str], list[str], list[str]]:
    """Phase I5/I7 — Aggregate topics across all perfumes under a brand.

    Joins entity_topic_links → entity_market filtered by brand_name='perfume'.
    Returns (top_topics, top_queries, top_subreddits, differentiators, positioning, intents).
    """
    from perfume_trend_sdk.analysis.topic_intelligence.semantic import classify_entity_topics
    try:
        rows = db.execute(text("""
            SELECT etl.topic_type, etl.topic_text,
                   COUNT(*) as occ,
                   COALESCE(AVG(etl.source_score), 0) as avg_score
            FROM entity_topic_links etl
            JOIN entity_market em ON CAST(em.id AS TEXT) = etl.entity_id
            WHERE em.brand_name = :bname AND em.entity_type = 'perfume'
            GROUP BY etl.topic_type, etl.topic_text
            ORDER BY occ DESC, avg_score DESC
        """), {"bname": brand_name}).fetchall()
    except Exception as exc:
        _log.warning("[I5] brand_topics query failed: %s", exc)
        return [], [], [], [], [], []

    topics: list[str] = []
    queries: list[str] = []
    subreddits: list[str] = []
    for ttype, ttext, _occ, _score in rows:
        if ttype == "topic" and len(topics) < limit_per_type:
            topics.append(ttext)
        elif ttype == "query" and len(queries) < limit_per_type:
            queries.append(ttext)
        elif ttype == "subreddit" and len(subreddits) < limit_per_type:
            subreddits.append(ttext)

    # Phase I7 — semantic classification
    raw_for_classify = [(r[0], r[1], int(r[2]), float(r[3])) for r in rows]
    profile = classify_entity_topics(raw_for_classify)
    return topics, queries, subreddits, profile.differentiators, profile.positioning, profile.intents


def _find_competitor_names(
    db: Session,
    entity_id_str: str,
    top_queries: list[str],
    current_canonical: str,
) -> list[str]:
    """Phase I8 — Detect competitor entities mentioned in comparison queries.

    Strategy:
      1. Extract VS-pattern candidates from raw queries.
      2. For each remaining orphan query (doesn't contain current entity name),
         look up entity_market for a canonical name contained within the query.
      Returns up to 5 resolved competitor canonical names.
    """
    from perfume_trend_sdk.analysis.topic_intelligence.market_intelligence import extract_vs_competitors
    try:
        vs_candidates = extract_vs_competitors(top_queries, current_canonical)
        if not vs_candidates:
            return []

        # Try to resolve candidates against tracked entity names
        competitors: list[str] = []
        seen: set[str] = set()
        own_lower = current_canonical.lower()

        for candidate in vs_candidates[:10]:
            c_lower = candidate.lower()
            row = db.execute(text("""
                SELECT canonical_name
                FROM entity_market
                WHERE entity_type = 'perfume'
                  AND LOWER(canonical_name) != :own
                  AND (
                    LOWER(:cand) LIKE '%' || LOWER(canonical_name) || '%'
                    OR LOWER(canonical_name) LIKE '%' || LOWER(:cand) || '%'
                  )
                  AND LENGTH(canonical_name) >= 5
                ORDER BY LENGTH(canonical_name) DESC
                LIMIT 1
            """), {"cand": candidate, "own": own_lower}).fetchone()

            if row and row[0].lower() not in seen and row[0].lower() != own_lower:
                seen.add(row[0].lower())
                competitors.append(row[0])
            elif not row and candidate not in seen and candidate.lower() != own_lower:
                # No DB match — include raw candidate string if long enough
                if len(candidate) >= 5:
                    seen.add(candidate.lower())
                    competitors.append(candidate)

            if len(competitors) >= 5:
                break

        return competitors
    except Exception as exc:
        _log.warning("[I8] competitor detection failed: %s", exc)
        return []


def _get_top_drivers(db: Session, entity_uuid, limit: int = 10) -> List[DriverRow]:
    """Phase I4 — Return top content drivers ordered by source quality + views.

    Each row is a distinct content item (deduplicated by source_url).
    Ordering: source_score DESC (quality), then views DESC (reach), then occurred_at DESC.
    Only rows with a mention_sources entry are returned — unscored rows are excluded
    because they carry no quality signal and would pollute the driver list.
    """
    try:
        rows = db.execute(text("""
            SELECT DISTINCT ON (COALESCE(em.source_url, em.id::text))
                em.source_platform,
                em.source_url,
                ms.source_name,
                em.source_url         AS title_url,
                ms.views,
                ms.likes,
                ms.comments_count,
                ms.engagement_rate,
                ms.source_score,
                em.occurred_at
            FROM entity_mentions em
            JOIN mention_sources ms ON ms.mention_id = em.id
            WHERE em.entity_id = :eid
              AND ms.source_score IS NOT NULL
            ORDER BY
                COALESCE(em.source_url, em.id::text),
                ms.source_score DESC,
                COALESCE(ms.views, 0) DESC,
                em.occurred_at DESC
        """), {"eid": str(entity_uuid)}).fetchall()
    except Exception as exc:
        _log.warning("[I4] top_drivers query failed: %s", exc)
        return []

    # Sort the deduplicated rows by source_score DESC, then views DESC
    rows_sorted = sorted(
        rows,
        key=lambda r: (-(r[8] or 0.0), -(r[4] or 0)),
    )[:limit]

    result = []
    for r in rows_sorted:
        result.append(DriverRow(
            source_platform=r[0],
            source_url=r[1],
            source_name=r[2],
            title=None,          # title not stored in entity_mentions; url is the identifier
            views=int(r[4]) if r[4] is not None else None,
            likes=int(r[5]) if r[5] is not None else None,
            comments_count=int(r[6]) if r[6] is not None else None,
            engagement_rate=float(r[7]) if r[7] is not None else None,
            source_score=float(r[8]) if r[8] is not None else None,
            occurred_at=_fmt_dt(r[9]) if r[9] else None,
        ))
    return result


def _get_top_drivers_for_brand(db: Session, brand_canonical_name: str, limit: int = 10) -> List[DriverRow]:
    """Phase I4 — Top drivers across all perfume entities of a brand.

    Brand entity_market rows don't have direct entity_mentions — individual
    perfume entities carry those.  This query aggregates across all perfumes
    whose brand_name matches the brand canonical name.
    """
    try:
        rows = db.execute(text("""
            SELECT DISTINCT ON (COALESCE(em.source_url, em.id::text))
                em.source_platform,
                em.source_url,
                ms.source_name,
                ms.views,
                ms.likes,
                ms.comments_count,
                ms.engagement_rate,
                ms.source_score,
                em.occurred_at
            FROM entity_mentions em
            JOIN entity_market e ON e.id = em.entity_id
            JOIN mention_sources ms ON ms.mention_id = em.id
            WHERE LOWER(e.brand_name) = LOWER(:brand)
              AND e.entity_type = 'perfume'
              AND ms.source_score IS NOT NULL
            ORDER BY
                COALESCE(em.source_url, em.id::text),
                ms.source_score DESC,
                COALESCE(ms.views, 0) DESC,
                em.occurred_at DESC
        """), {"brand": brand_canonical_name}).fetchall()
    except Exception as exc:
        _log.warning("[I4] top_drivers_for_brand query failed: %s", exc)
        return []

    rows_sorted = sorted(
        rows,
        key=lambda r: (-(r[7] or 0.0), -(r[3] or 0)),
    )[:limit]

    return [
        DriverRow(
            source_platform=r[0],
            source_url=r[1],
            source_name=r[2],
            title=None,
            views=int(r[3]) if r[3] is not None else None,
            likes=int(r[4]) if r[4] is not None else None,
            comments_count=int(r[5]) if r[5] is not None else None,
            engagement_rate=float(r[6]) if r[6] is not None else None,
            source_score=float(r[7]) if r[7] is not None else None,
            occurred_at=_fmt_dt(r[8]) if r[8] else None,
        )
        for r in rows_sorted
    ]


def _build_summary(
    em: EntityMarket,
    latest,
    brand_name: Optional[str],
) -> Dict[str, Any]:
    """Build a flat, structured summary dict for the entity detail page."""
    return {
        "entity_id": em.entity_id,
        "entity_type": em.entity_type,
        "name": em.canonical_name,
        "ticker": em.ticker,
        "brand_name": brand_name,
        # Latest snapshot metrics (None if no snapshot yet)
        "last_score": latest.composite_market_score if latest else None,
        "mention_count": latest.mention_count if latest else None,
        "growth_rate": latest.growth_rate if latest else None,
        "confidence_avg": latest.confidence_avg if latest else None,
        "momentum": latest.momentum if latest else None,
        "acceleration": latest.acceleration if latest else None,
        "volatility": latest.volatility if latest else None,
        "latest_date": latest.date.isoformat() if latest and latest.date else None,
    }


# ---------------------------------------------------------------------------
# Phase U2 — type-specific entity schemas
# ---------------------------------------------------------------------------

class BrandPerfumeRow(BaseModel):
    entity_id: Optional[str] = None
    resolver_id: Optional[int] = None
    canonical_name: str
    has_activity_today: bool = False
    latest_score: Optional[float] = None
    mention_count: Optional[float] = None


class SimilarPerfumeRow(BaseModel):
    canonical_name: str
    brand_name: Optional[str] = None
    resolver_id: Optional[int] = None
    entity_id: Optional[str] = None   # set when tracked in market engine
    shared_notes: int = 0


class PerfumeEntityDetail(BaseModel):
    """Richer perfume entity response — works for tracked AND catalog-only entities."""
    id: str
    resolver_id: Optional[int] = None
    entity_type: str = "perfume"
    canonical_name: str
    brand_name: Optional[str] = None
    ticker: Optional[str] = None
    state: str  # "active" | "tracked" | "catalog_only"
    # Phase I7.5 — Entity role classification
    entity_role: str = "unknown"  # "designer_original" | "niche_original" | "unknown" | …
    has_activity_today: bool = False
    aliases_count: int = 0
    # Market metrics — None for catalog_only
    latest_score: Optional[float] = None
    latest_growth: Optional[float] = None
    latest_signal: Optional[str] = None
    latest_date: Optional[str] = None
    confidence_avg: Optional[float] = None
    momentum: Optional[float] = None
    # Phase I3 — directional trend state for the most recent active day
    trend_state: Optional[str] = None
    # Time series + events
    timeseries: List[SnapshotRow] = []
    recent_signals: List[SignalRow] = []
    recent_mentions: List[RecentMentionRow] = []
    top_drivers: List[DriverRow] = []   # Phase I4 — highest-impact content items
    # Phase I5 — Why it's trending (deterministic topic/query intelligence)
    top_topics: List[str] = []     # semantic labels: "compliment getter", "blind buy", …
    top_queries: List[str] = []    # YouTube search queries that surfaced this entity
    top_subreddits: List[str] = [] # Reddit communities discussing this entity
    # Phase I7 — Semantic profile (classified from I5/I6 topic links)
    differentiators: List[str] = []  # what makes it unique: "dupe / alternative", "longevity / projection", …
    positioning: List[str] = []      # what it is: "vanilla", "niche fragrance", "men's fragrance", …
    intents: List[str] = []          # why people search: queries + "review", "gift idea", "new release", …
    # Phase I8 — Market Intelligence
    narrative: Optional[str] = None   # plain-language reason why it is trending
    opportunities: List[str] = []     # market flags: "dupe_market", "high_intent", "gifting", …
    competitors: List[str] = []       # detected competitor entity names
    # Enrichment
    notes_top: List[str] = []
    notes_middle: List[str] = []
    notes_base: List[str] = []
    accords: List[str] = []
    notes_source: Optional[str] = None   # "fragrantica" | "parfumo"
    similar_perfumes: List[SimilarPerfumeRow] = []
    # Brand navigation — entity_id slug for the brand entity page (if the brand is tracked)
    brand_entity_id: Optional[str] = None


class BrandEntityDetail(BaseModel):
    """Richer brand entity response — works for tracked AND catalog-only entities."""
    id: str
    resolver_id: Optional[int] = None
    entity_type: str = "brand"
    canonical_name: str
    ticker: Optional[str] = None
    state: str  # "active" | "tracked" | "catalog_only"
    has_activity_today: bool = False
    perfume_count: int = 0       # total perfumes in KB for this brand
    active_perfume_count: int = 0
    # Market metrics — None for catalog_only
    latest_score: Optional[float] = None
    latest_growth: Optional[float] = None
    latest_signal: Optional[str] = None
    # Phase I3 — directional trend state for the most recent active day
    trend_state: Optional[str] = None
    # Linked perfumes — catalog_perfumes: all from resolver (up to 100)
    # top_perfumes kept for backward compat (same data as catalog_perfumes)
    catalog_perfumes: List[BrandPerfumeRow] = []
    top_perfumes: List[BrandPerfumeRow] = []   # alias: same list
    timeseries: List[SnapshotRow] = []
    recent_signals: List[SignalRow] = []
    top_drivers: List[DriverRow] = []   # Phase I4 — highest-impact content items
    # Phase I5 — Why it's trending (aggregated across brand portfolio)
    top_topics: List[str] = []
    top_queries: List[str] = []
    top_subreddits: List[str] = []
    # Phase I7 — Semantic profile (classified from I5/I6 topic links)
    differentiators: List[str] = []
    positioning: List[str] = []
    intents: List[str] = []
    # Phase I8 — Market Intelligence
    narrative: Optional[str] = None
    opportunities: List[str] = []
    competitors: List[str] = []
    # Aggregated notes/accords across brand portfolio
    top_notes: List[str] = []
    top_accords: List[str] = []


# ---------------------------------------------------------------------------
# Phase U2 — helpers
# ---------------------------------------------------------------------------

def _safe(fn, fallback, label: str = ""):
    try:
        return fn()
    except Exception as exc:
        _log.warning("[U2] %s failed: %s", label or "query", exc)
        return fallback


def _check_activity_today(db: Session, entity_uuid) -> bool:
    row = _safe(lambda: db.execute(
        text("""
        SELECT 1 FROM entity_timeseries_daily
        WHERE entity_id = :uuid
          AND date = (SELECT MAX(date) FROM entity_timeseries_daily WHERE mention_count > 0)
          AND mention_count > 0
        LIMIT 1
        """),
        {"uuid": str(entity_uuid)},
    ).fetchone(), None, "activity_today")
    return row is not None


def _resolver_id_for(db: Session, canonical_name: str, entity_type: str) -> Optional[int]:
    table = "resolver_perfumes" if entity_type == "perfume" else "resolver_brands"
    row = _safe(lambda: db.execute(
        text(f"SELECT id FROM {table} WHERE LOWER(canonical_name) = LOWER(:n) LIMIT 1"),
        {"n": canonical_name},
    ).fetchone(), None, f"resolver_id({entity_type})")
    return int(row[0]) if row else None


def _brand_entity_id_for(db: Session, brand_name: Optional[str]) -> Optional[str]:
    """Return the entity_id slug for a brand from entity_market, or None."""
    if not brand_name:
        return None
    row = _safe(lambda: db.execute(
        text("SELECT entity_id FROM entity_market WHERE entity_type='brand' AND LOWER(canonical_name) = LOWER(:n) LIMIT 1"),
        {"n": brand_name},
    ).fetchone(), None, "brand_entity_id")
    return str(row[0]) if row else None


def _aliases_count(db: Session, resolver_id: int, entity_type: str) -> int:
    row = _safe(lambda: db.execute(
        text("SELECT COUNT(*) FROM resolver_aliases WHERE entity_id = :rid AND entity_type = :et"),
        {"rid": resolver_id, "et": entity_type},
    ).fetchone(), None, "aliases_count")
    return int(row[0]) if row else 0


def _fragrantica_notes(db: Session, entity_id_slug: str):
    """Fetch notes / accords from fragrantica_records via perfumes.slug join."""
    row = _safe(lambda: db.execute(
        text("""
        SELECT fr.notes_top_json, fr.notes_middle_json, fr.notes_base_json, fr.accords_json
        FROM fragrantica_records fr
        JOIN perfumes p ON CAST(p.id AS TEXT) = fr.perfume_id
        WHERE p.slug = :slug
        LIMIT 1
        """),
        {"slug": entity_id_slug},
    ).fetchone(), None, "fragrantica_notes")
    if not row:
        return [], [], [], []
    return (
        _safe(lambda: json.loads(row[0] or "[]"), [], "notes_top"),
        _safe(lambda: json.loads(row[1] or "[]"), [], "notes_mid"),
        _safe(lambda: json.loads(row[2] or "[]"), [], "notes_base"),
        _safe(lambda: json.loads(row[3] or "[]"), [], "accords"),
    )


def _resolver_notes(db: Session, resolver_id: int):
    """Fetch notes / accords from resolver_perfume_notes (Phase 1B dataset fallback)."""
    if not resolver_id:
        return [], [], [], []
    notes_rows = _safe(lambda: db.execute(
        text("""
        SELECT note_name, position
        FROM resolver_perfume_notes
        WHERE resolver_perfume_id = :rid
        ORDER BY position, note_name
        """),
        {"rid": resolver_id},
    ).fetchall(), None, "resolver_notes")
    accords_rows = _safe(lambda: db.execute(
        text("""
        SELECT accord_name
        FROM resolver_perfume_accords
        WHERE resolver_perfume_id = :rid
        ORDER BY accord_name
        """),
        {"rid": resolver_id},
    ).fetchall(), None, "resolver_accords")
    if notes_rows is None and accords_rows is None:
        return [], [], [], []
    top = [r[0] for r in (notes_rows or []) if r[1] == "top"]
    middle = [r[0] for r in (notes_rows or []) if r[1] == "middle"]
    base = [r[0] for r in (notes_rows or []) if r[1] == "base"]
    accords = [r[0] for r in (accords_rows or [])]
    return top, middle, base, accords


def _get_perfume_notes(db: Session, entity_id_slug: str, resolver_id: Optional[int]):
    """Return (top, mid, base, acc, source) preferring fragrantica then falling back to resolver_perfume_notes."""
    top, mid, base, acc = _fragrantica_notes(db, entity_id_slug)
    if top or mid or base or acc:
        return top, mid, base, acc, "fragrantica"
    # Fallback: dataset-imported notes (Phase 1B)
    top, mid, base, acc = _resolver_notes(db, resolver_id)
    if top or mid or base or acc:
        return top, mid, base, acc, "parfumo"
    return [], [], [], [], None


def _similar_by_notes(db: Session, resolver_id: int, limit: int = 8) -> List[SimilarPerfumeRow]:
    """Find perfumes that share the most notes with the given resolver perfume."""
    if not resolver_id:
        return []
    rows = _safe(lambda: db.execute(
        text("""
        SELECT
            rp2.id,
            rp2.canonical_name,
            rb2.canonical_name,
            em.entity_id,
            COUNT(*) AS shared_notes
        FROM resolver_perfume_notes rpn1
        JOIN resolver_perfume_notes rpn2
            ON rpn1.normalized_name = rpn2.normalized_name
           AND rpn2.resolver_perfume_id != :rid
        JOIN resolver_perfumes rp2 ON rp2.id = rpn2.resolver_perfume_id
        LEFT JOIN resolver_brands rb2 ON rb2.id = rp2.brand_id
        LEFT JOIN entity_market em
            ON LOWER(em.canonical_name) = LOWER(rp2.canonical_name)
           AND em.entity_type = 'perfume'
        WHERE rpn1.resolver_perfume_id = :rid
        GROUP BY rp2.id, rp2.canonical_name, rb2.canonical_name, em.entity_id
        ORDER BY shared_notes DESC, rp2.canonical_name
        LIMIT :lim
        """),
        {"rid": resolver_id, "lim": limit},
    ).fetchall(), [], "similar_by_notes")
    return [
        SimilarPerfumeRow(
            resolver_id=int(r[0]),
            canonical_name=r[1],
            brand_name=r[2],
            entity_id=r[3],
            shared_notes=int(r[4]),
        )
        for r in rows
    ]


def _brand_perfume_count(db: Session, brand_canonical_name: str) -> int:
    row = _safe(lambda: db.execute(
        text("""
        SELECT COUNT(*) FROM resolver_perfumes rp
        JOIN resolver_brands rb ON rp.brand_id = rb.id
        WHERE LOWER(rb.canonical_name) = LOWER(:n)
        """),
        {"n": brand_canonical_name},
    ).fetchone(), None, "brand_perfume_count")
    return int(row[0]) if row else 0


def _brand_active_perfume_count(db: Session, brand_canonical_name: str) -> int:
    row = _safe(lambda: db.execute(
        text("""
        SELECT COUNT(DISTINCT em.id)
        FROM entity_market em
        JOIN entity_timeseries_daily etd ON etd.entity_id = em.id
        WHERE em.entity_type = 'perfume'
          AND LOWER(em.brand_name) = LOWER(:n)
          AND etd.date = (SELECT MAX(date) FROM entity_timeseries_daily WHERE mention_count > 0)
          AND etd.mention_count > 0
        """),
        {"n": brand_canonical_name},
    ).fetchone(), None, "brand_active_perfumes")
    return int(row[0]) if row else 0


def _brand_top_notes(db: Session, brand_canonical_name: str, limit: int = 15) -> List[str]:
    """Aggregate top notes across all brand perfumes in the KB."""
    rows = _safe(lambda: db.execute(
        text("""
        SELECT rpn.note_name, COUNT(*) AS cnt
        FROM resolver_perfumes rp
        JOIN resolver_brands rb ON rp.brand_id = rb.id
        JOIN resolver_perfume_notes rpn ON rpn.resolver_perfume_id = rp.id
        WHERE LOWER(rb.canonical_name) = LOWER(:n)
        GROUP BY rpn.note_name
        ORDER BY cnt DESC
        LIMIT :lim
        """),
        {"n": brand_canonical_name, "lim": limit},
    ).fetchall(), [], "brand_top_notes")
    return [r[0] for r in rows]


def _brand_top_accords(db: Session, brand_canonical_name: str, limit: int = 10) -> List[str]:
    """Aggregate top accords across all brand perfumes in the KB."""
    rows = _safe(lambda: db.execute(
        text("""
        SELECT rpa.accord_name, COUNT(*) AS cnt
        FROM resolver_perfumes rp
        JOIN resolver_brands rb ON rp.brand_id = rb.id
        JOIN resolver_perfume_accords rpa ON rpa.resolver_perfume_id = rp.id
        WHERE LOWER(rb.canonical_name) = LOWER(:n)
        GROUP BY rpa.accord_name
        ORDER BY cnt DESC
        LIMIT :lim
        """),
        {"n": brand_canonical_name, "lim": limit},
    ).fetchall(), [], "brand_top_accords")
    return [r[0] for r in rows]


def _brand_catalog_perfumes(db: Session, brand_canonical_name: str, limit: int = 100) -> List[BrandPerfumeRow]:
    """Return all catalog perfumes for a brand from resolver_perfumes (source of truth).

    LEFT JOINs to entity_market + entity_timeseries_daily to populate market data
    where available. Catalog-only perfumes (no ingested data) are included with
    entity_id=None and all market fields null. Eligibility filter from Phase E1
    is applied to hide malformed KB entries.
    """
    rows = _safe(lambda: db.execute(
        text("""
        WITH latest_date_per_entity AS (
            SELECT entity_id, MAX(date) AS latest_date
            FROM entity_timeseries_daily
            WHERE mention_count > 0
            GROUP BY entity_id
        )
        SELECT
            em.entity_id,
            rp.canonical_name,
            etd.composite_market_score,
            etd.mention_count,
            CASE WHEN etd.mention_count > 0 THEN true ELSE false END AS has_activity_today,
            rp.id AS resolver_id
        FROM resolver_perfumes rp
        JOIN resolver_brands rb ON rp.brand_id = rb.id
        LEFT JOIN entity_market em
            ON LOWER(em.canonical_name) = LOWER(rp.canonical_name)
            AND em.entity_type = 'perfume'
        LEFT JOIN latest_date_per_entity ld ON ld.entity_id = em.id
        LEFT JOIN entity_timeseries_daily etd
            ON etd.entity_id = em.id AND etd.date = ld.latest_date
        WHERE LOWER(rb.canonical_name) = LOWER(:n)
          AND LENGTH(REGEXP_REPLACE(rp.canonical_name, '[^a-zA-Z]', '', 'g')) >= 2
          AND rp.canonical_name ~ '^[a-zA-Z0-9]'
          AND LOWER(rp.canonical_name) NOT IN
              ('cologne','fragrance','perfume','scent','mist','spray')
        ORDER BY COALESCE(etd.composite_market_score, 0) DESC,
                 rp.canonical_name ASC
        LIMIT :lim
        """),
        {"n": brand_canonical_name, "lim": limit},
    ).fetchall(), [], "brand_catalog_perfumes")
    return [
        BrandPerfumeRow(
            entity_id=r[0],
            canonical_name=r[1],
            latest_score=float(r[2]) if r[2] is not None else None,
            mention_count=float(r[3]) if r[3] is not None else None,
            has_activity_today=bool(r[4]) if r[4] is not None else False,
            resolver_id=int(r[5]) if r[5] is not None else None,
        )
        for r in rows
    ]


def _build_snapshot_rows(history_rows) -> List[SnapshotRow]:
    return [
        SnapshotRow(
            date=r.date.isoformat(),
            mention_count=r.mention_count or 0.0,
            unique_authors=r.unique_authors or 0,
            engagement_sum=r.engagement_sum or 0.0,
            composite_market_score=r.composite_market_score or 0.0,
            weighted_signal_score=getattr(r, "weighted_signal_score", None),
            confidence_avg=r.confidence_avg,
            momentum=r.momentum,
            acceleration=r.acceleration,
            volatility=r.volatility,
            growth_rate=r.growth_rate,
            search_index=r.search_index,
            retailer_score=r.retailer_score,
            trend_state=getattr(r, "trend_state", None),  # Phase I3
        )
        for r in history_rows
    ]


def _build_signal_rows(signal_rows, em: EntityMarket, brand_name: Optional[str]) -> List[SignalRow]:
    return [
        SignalRow(
            entity_id=em.entity_id,
            signal_type=s.signal_type,
            detected_at=_fmt_dt(s.detected_at),
            strength=s.strength or 0.0,
            confidence=s.confidence,
            entity_type=s.entity_type,
            ticker=em.ticker,
            canonical_name=em.canonical_name,
            brand_name=brand_name,
            metadata_json=s.metadata_json,
        )
        for s in signal_rows
    ]


def _build_mention_rows(mention_rows) -> List[RecentMentionRow]:
    rows = []
    for m in mention_rows:
        if isinstance(m, dict):
            occurred = m.get("occurred_at")
            rows.append(RecentMentionRow(
                source_platform=m.get("source_platform"),
                source_url=m.get("source_url"),
                author_name=m.get("author_name") or m.get("author_id"),
                engagement=m.get("engagement"),
                occurred_at=_fmt_dt(occurred) if occurred else "",
                views=m.get("views"),
                likes=m.get("likes"),
                comments_count=m.get("comments_count"),
                engagement_rate=m.get("engagement_rate"),
            ))
        else:
            # ORM object fallback
            rows.append(RecentMentionRow(
                source_platform=m.source_platform,
                source_url=m.source_url,
                author_name=m.author_name or m.author_id,
                engagement=m.engagement,
                occurred_at=_fmt_dt(m.occurred_at),
            ))
    return rows


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=List[EntitySummary])
def list_entities(db: Session = Depends(get_db_session)) -> List[EntitySummary]:
    rows = fetch_latest_rows(db)
    brand_name_map = fetch_brand_name_map(db)
    latest_signal_map = fetch_latest_signal_map(db)

    result = []
    for em, snap in rows:
        sig_info = latest_signal_map.get(em.id)
        result.append(EntitySummary(
            entity_id=em.entity_id,
            entity_type=em.entity_type,
            ticker=em.ticker,
            canonical_name=em.canonical_name,
            brand_name=get_brand_name(em, brand_name_map),
            date=snap.date.isoformat() if snap and snap.date else None,
            mention_count=snap.mention_count if snap else None,
            engagement_sum=snap.engagement_sum if snap else None,
            composite_market_score=snap.composite_market_score if snap else None,
            confidence_avg=snap.confidence_avg if snap else None,
            momentum=snap.momentum if snap else None,
            acceleration=snap.acceleration if snap else None,
            volatility=snap.volatility if snap else None,
            growth_rate=snap.growth_rate if snap else None,
            latest_signal_type=sig_info[0] if sig_info else None,
            latest_signal_strength=sig_info[1] if sig_info else None,
        ))
    return result


# ---------------------------------------------------------------------------
# POST /api/v1/entities/start-tracking
# Create a minimal entity_market row for a catalog-only entity.
# This enables catalog-only entities to be watchlisted.
# MUST be defined before /perfume/{id} and /brand/{id} to avoid shadowing.
# ---------------------------------------------------------------------------

def _slugify(s: str) -> str:
    """Lowercase, collapse non-alphanumeric chars to dashes."""
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _generate_ticker(canonical_name: str, entity_type: str, max_len: int = 6) -> str:
    """Generate a short ticker from a canonical name."""
    if entity_type == "brand":
        words = canonical_name.upper().split()
        if len(words) == 1:
            return words[0][:max_len]
        return "".join(w[0] for w in words)[:max_len]
    # perfume: use significant words, skip "de", "du", "la", etc.
    stop = {"de", "du", "la", "le", "les", "for", "of", "and", "the", "von", "der"}
    words = [w for w in canonical_name.upper().split() if w.lower() not in stop]
    if not words:
        words = canonical_name.upper().split()
    if len(words) == 1:
        return words[0][:max_len]
    return "".join(w[0] for w in words[:max_len])


class StartTrackingRequest(BaseModel):
    resolver_id: int
    entity_type: str  # "perfume" | "brand"


class StartTrackingResponse(BaseModel):
    entity_id: str
    canonical_name: str
    already_tracked: bool = False


@router.post("/start-tracking", response_model=StartTrackingResponse, status_code=201)
def start_tracking(
    body: StartTrackingRequest,
    db: Session = Depends(get_db_session),
) -> StartTrackingResponse:
    """Create a minimal entity_market row for a catalog-only entity.

    Enables catalog-only entities (known in the resolver KB but not yet
    encountered in ingested content) to be added to watchlists.
    """
    if body.entity_type not in ("perfume", "brand"):
        raise HTTPException(status_code=400, detail="entity_type must be 'perfume' or 'brand'")

    # Look up in resolver catalog
    table = "resolver_perfumes" if body.entity_type == "perfume" else "resolver_brands"
    row = _safe(lambda: db.execute(
        text(f"""
        SELECT rp.canonical_name{', rb.canonical_name AS brand_name' if body.entity_type == 'perfume' else ', NULL AS brand_name'}
        FROM {table} rp
        {'LEFT JOIN resolver_brands rb ON rp.brand_id = rb.id' if body.entity_type == 'perfume' else ''}
        WHERE rp.id = :rid
        LIMIT 1
        """),
        {"rid": body.resolver_id},
    ).fetchone(), None, "start_tracking_lookup")

    if not row:
        raise HTTPException(status_code=404, detail=f"Resolver entity not found: {body.resolver_id}")

    canonical_name: str = row[0]
    brand_name: Optional[str] = row[1] if len(row) > 1 else None

    # Compute the slug entity_id
    if body.entity_type == "brand":
        entity_id = f"brand-{_slugify(canonical_name)}"
    else:
        entity_id = _slugify(canonical_name)

    # Check if already tracked
    existing = db.query(EntityMarket).filter_by(entity_id=entity_id).first()
    if existing:
        return StartTrackingResponse(
            entity_id=existing.entity_id,
            canonical_name=existing.canonical_name,
            already_tracked=True,
        )

    # Create minimal entity_market row
    ticker = _generate_ticker(canonical_name, body.entity_type)
    em = EntityMarket(
        id=_uuid_mod.uuid4(),
        entity_id=entity_id,
        entity_type=body.entity_type,
        ticker=ticker,
        canonical_name=canonical_name,
        brand_name=brand_name if body.entity_type == "perfume" else None,
    )
    db.add(em)
    db.flush()

    _log.info(
        "start_tracking entity_id=%s type=%s canonical_name=%s",
        entity_id,
        body.entity_type,
        canonical_name,
    )

    return StartTrackingResponse(
        entity_id=entity_id,
        canonical_name=canonical_name,
        already_tracked=False,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/entities/perfume/{id}
# {id} = entity_id slug (tracked) OR resolver_id integer string (catalog-only)
# MUST be defined before /{entity_id:path} to avoid catch-all shadowing.
# ---------------------------------------------------------------------------

@router.get("/perfume/{id}", response_model=PerfumeEntityDetail)
def get_perfume_entity(
    id: str,
    history_days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db_session),
) -> PerfumeEntityDetail:
    # Step 1: try slug lookup (tracked entity in entity_market)
    em = db.query(EntityMarket).filter(
        EntityMarket.entity_id == id,
        EntityMarket.entity_type == "perfume",
    ).first()

    if em:
        has_activity = _check_activity_today(db, em.id)
        state = "active" if has_activity else "tracked"

        latest = _safe(lambda: _get_latest_snapshot(db, em.id), None, "latest_snap")
        history_rows = _safe(lambda: _get_history(db, em.id, days=history_days), [], "history")
        signal_rows = _safe(lambda: _get_signals(db, em.id, limit=20), [], "signals")
        mention_rows = _safe(lambda: _get_recent_mentions(db, em.id, limit=5), [], "mentions")

        resolver_id = _resolver_id_for(db, em.canonical_name, "perfume")
        aliases = _aliases_count(db, resolver_id, "perfume") if resolver_id else 0
        notes_top, notes_mid, notes_base, accords, notes_source = _get_perfume_notes(db, em.entity_id, resolver_id)
        similar = _similar_by_notes(db, resolver_id) if resolver_id else []
        drivers = _safe(lambda: _get_top_drivers(db, em.id, limit=10), [], "top_drivers")
        # Phase I5/I7 — topic/query intelligence + semantic profile
        p_topics, p_queries, p_subs, p_diff, p_pos, p_intents = _safe(
            lambda: _get_entity_topics(db, str(em.id)), ([], [], [], [], [], []), "entity_topics"
        )
        # Phase I8 — Market Intelligence
        p_competitors = _safe(
            lambda: _find_competitor_names(db, str(em.id), p_queries, em.canonical_name),
            [], "competitors",
        )
        _ts = getattr(latest, "trend_state", None) if latest else None
        from perfume_trend_sdk.analysis.topic_intelligence.market_intelligence import generate_market_intelligence
        p_intelligence = _safe(
            lambda: generate_market_intelligence(
                canonical_name=em.canonical_name,
                differentiators=p_diff,
                positioning=p_pos,
                intents=p_intents,
                raw_queries=p_queries,
                resolved_competitors=p_competitors,
                trend_state=_ts,
            ),
            None, "market_intelligence",
        )
        latest_sig = signal_rows[0].signal_type if signal_rows else None

        brand_entity_id = _brand_entity_id_for(db, em.brand_name)
        p_role = classify_entity_role(em.brand_name, em.canonical_name)  # Phase I7.5
        return PerfumeEntityDetail(
            id=em.entity_id,
            resolver_id=resolver_id,
            canonical_name=em.canonical_name,
            brand_name=em.brand_name,
            ticker=em.ticker,
            state=state,
            entity_role=p_role,      # Phase I7.5
            has_activity_today=has_activity,
            aliases_count=aliases,
            latest_score=latest.composite_market_score if latest else None,
            latest_growth=latest.growth_rate if latest else None,
            latest_signal=latest_sig,
            latest_date=latest.date.isoformat() if latest and latest.date else None,
            confidence_avg=latest.confidence_avg if latest else None,
            momentum=latest.momentum if latest else None,
            trend_state=getattr(latest, "trend_state", None) if latest else None,  # Phase I3
            timeseries=_build_snapshot_rows(history_rows),
            recent_signals=_build_signal_rows(signal_rows, em, em.brand_name),
            recent_mentions=_build_mention_rows(mention_rows),
            top_drivers=drivers,
            top_topics=p_topics,    # Phase I5
            top_queries=p_queries,  # Phase I5
            top_subreddits=p_subs,  # Phase I5
            differentiators=p_diff,  # Phase I7
            positioning=p_pos,       # Phase I7
            intents=p_intents,       # Phase I7
            narrative=p_intelligence.narrative if p_intelligence else None,   # Phase I8
            opportunities=p_intelligence.opportunities if p_intelligence else [],  # Phase I8
            competitors=p_intelligence.competitors if p_intelligence else [],  # Phase I8
            notes_top=notes_top,
            notes_middle=notes_mid,
            notes_base=notes_base,
            accords=accords,
            notes_source=notes_source,
            similar_perfumes=similar,
            brand_entity_id=brand_entity_id,
        )

    # Step 2: try catalog-only lookup via resolver_id
    try:
        resolver_id = int(id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Perfume not found: {id}")

    rp_row = _safe(lambda: db.execute(
        text("""
        SELECT rp.id, rp.canonical_name, rb.canonical_name AS brand_name
        FROM resolver_perfumes rp
        LEFT JOIN resolver_brands rb ON rp.brand_id = rb.id
        WHERE rp.id = :rid
        """),
        {"rid": resolver_id},
    ).fetchone(), None, "resolver_perfume_lookup")

    if not rp_row:
        raise HTTPException(status_code=404, detail=f"Perfume not found: {id}")

    aliases = _aliases_count(db, resolver_id, "perfume")
    cat_top, cat_mid, cat_base, cat_acc = _resolver_notes(db, resolver_id)
    cat_source = "parfumo" if (cat_top or cat_mid or cat_base or cat_acc) else None
    similar = _similar_by_notes(db, resolver_id)
    brand_entity_id = _brand_entity_id_for(db, rp_row[2])
    cat_role = classify_entity_role(rp_row[2], rp_row[1])  # Phase I7.5
    return PerfumeEntityDetail(
        id=str(resolver_id),
        resolver_id=resolver_id,
        canonical_name=rp_row[1],
        brand_name=rp_row[2],
        state="catalog_only",
        entity_role=cat_role,  # Phase I7.5
        aliases_count=aliases,
        notes_top=cat_top,
        notes_middle=cat_mid,
        notes_base=cat_base,
        accords=cat_acc,
        notes_source=cat_source,
        similar_perfumes=similar,
        brand_entity_id=brand_entity_id,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/entities/brand/{id}
# {id} = entity_id slug (tracked) OR resolver_id integer string (catalog-only)
# MUST be defined before /{entity_id:path}.
# ---------------------------------------------------------------------------

@router.get("/brand/{id}", response_model=BrandEntityDetail)
def get_brand_entity(
    id: str,
    history_days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db_session),
) -> BrandEntityDetail:
    # Step 1: try slug lookup (tracked entity in entity_market)
    em = db.query(EntityMarket).filter(
        EntityMarket.entity_id == id,
        EntityMarket.entity_type == "brand",
    ).first()

    if em:
        has_activity = _check_activity_today(db, em.id)
        state = "active" if has_activity else "tracked"

        latest = _safe(lambda: _get_latest_snapshot(db, em.id), None, "brand_snap")
        history_rows = _safe(lambda: _get_history(db, em.id, days=history_days), [], "brand_hist")
        signal_rows = _safe(lambda: _get_signals(db, em.id, limit=20), [], "brand_sigs")

        perfume_count = _brand_perfume_count(db, em.canonical_name)
        active_count = _brand_active_perfume_count(db, em.canonical_name)
        catalog_perfumes = _brand_catalog_perfumes(db, em.canonical_name)
        top_notes = _brand_top_notes(db, em.canonical_name)
        top_accords = _brand_top_accords(db, em.canonical_name)
        drivers = _safe(lambda: _get_top_drivers_for_brand(db, em.canonical_name, limit=10), [], "brand_top_drivers")
        b_topics, b_queries, b_subs, b_diff, b_pos, b_intents = _safe(
            lambda: _get_brand_topics(db, em.canonical_name), ([], [], [], [], [], []), "brand_topics"
        )
        # Phase I8 — Brand market intelligence (no competitor detection for brands in V1)
        _b_ts = getattr(latest, "trend_state", None) if latest else None
        from perfume_trend_sdk.analysis.topic_intelligence.market_intelligence import generate_market_intelligence as _gen_intel
        b_intelligence = _safe(
            lambda: _gen_intel(
                canonical_name=em.canonical_name,
                differentiators=b_diff,
                positioning=b_pos,
                intents=b_intents,
                raw_queries=b_queries,
                resolved_competitors=[],
                trend_state=_b_ts,
            ),
            None, "brand_market_intelligence",
        )

        resolver_id = _resolver_id_for(db, em.canonical_name, "brand")
        latest_sig = signal_rows[0].signal_type if signal_rows else None

        return BrandEntityDetail(
            id=em.entity_id,
            resolver_id=resolver_id,
            canonical_name=em.canonical_name,
            ticker=em.ticker,
            state=state,
            has_activity_today=has_activity,
            perfume_count=perfume_count,
            active_perfume_count=active_count,
            latest_score=latest.composite_market_score if latest else None,
            latest_growth=latest.growth_rate if latest else None,
            latest_signal=latest_sig,
            trend_state=getattr(latest, "trend_state", None) if latest else None,  # Phase I3
            catalog_perfumes=catalog_perfumes,
            top_perfumes=catalog_perfumes,
            timeseries=_build_snapshot_rows(history_rows),
            recent_signals=_build_signal_rows(signal_rows, em, None),
            top_drivers=drivers,
            top_notes=top_notes,
            top_accords=top_accords,
            top_topics=b_topics,
            top_queries=b_queries,
            top_subreddits=b_subs,
            differentiators=b_diff,  # Phase I7
            positioning=b_pos,       # Phase I7
            intents=b_intents,       # Phase I7
            narrative=b_intelligence.narrative if b_intelligence else None,    # Phase I8
            opportunities=b_intelligence.opportunities if b_intelligence else [],  # Phase I8
            competitors=b_intelligence.competitors if b_intelligence else [],  # Phase I8
        )

    # Step 2: try catalog-only lookup via resolver_id
    try:
        resolver_id = int(id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Brand not found: {id}")

    rb_row = _safe(lambda: db.execute(
        text("SELECT id, canonical_name FROM resolver_brands WHERE id = :rid"),
        {"rid": resolver_id},
    ).fetchone(), None, "resolver_brand_lookup")

    if not rb_row:
        raise HTTPException(status_code=404, detail=f"Brand not found: {id}")

    perfume_count = _brand_perfume_count(db, rb_row[1])
    catalog_perfumes = _brand_catalog_perfumes(db, rb_row[1])
    top_notes = _brand_top_notes(db, rb_row[1])
    top_accords = _brand_top_accords(db, rb_row[1])
    return BrandEntityDetail(
        id=str(resolver_id),
        resolver_id=resolver_id,
        canonical_name=rb_row[1],
        state="catalog_only",
        perfume_count=perfume_count,
        catalog_perfumes=catalog_perfumes,
        top_perfumes=catalog_perfumes,
        top_notes=top_notes,
        top_accords=top_accords,
    )


# ---------------------------------------------------------------------------
# Phase C1 Product/API — Top creators for a perfume or brand entity page
# GET /api/v1/entities/perfume/{id}/creators
# GET /api/v1/entities/brand/{id}/creators
# Must be defined before the /{entity_id:path} catch-all routes.
# ---------------------------------------------------------------------------

def _get_entity_creators(
    db: Session,
    entity_id_slug: str,
    entity_type: str,
    limit: int,
) -> list:
    """Query top creators for an entity by its entity_id slug.

    Joins creator_entity_relationships with creator_scores to include influence_score
    and early_signal_count. Ordered by mention_count DESC, total_views DESC.
    Returns empty list if entity not found or creator tables unavailable.
    """
    from perfume_trend_sdk.api.schemas.creators import EntityCreatorsResponse, TopCreatorRow

    # Resolve slug → UUID in entity_market
    em_row = _safe(
        lambda: db.execute(
            text("SELECT id FROM entity_market WHERE entity_id = :slug AND entity_type = :et LIMIT 1"),
            {"slug": entity_id_slug, "et": entity_type},
        ).fetchone(),
        None,
        "entity_creators_lookup",
    )

    if not em_row:
        return []

    entity_uuid = str(em_row[0])

    try:
        rows = db.execute(text("""
            SELECT
                cer.platform,
                cer.creator_id,
                cer.creator_handle,
                cer.entity_type      AS rel_entity_type,
                cer.mention_count,
                cer.unique_content_count,
                cer.first_mention_date,
                cer.last_mention_date,
                cer.total_views,
                cer.avg_views,
                cer.total_likes,
                cer.total_comments,
                cer.avg_engagement_rate,
                cer.mentions_before_first_breakout,
                cer.days_before_first_breakout,
                cs.influence_score,
                cs.early_signal_count,
                cs.quality_tier,
                cs.category
            FROM creator_entity_relationships cer
            LEFT JOIN creator_scores cs
                ON cs.platform = cer.platform AND cs.creator_id = cer.creator_id
            WHERE CAST(cer.entity_id AS TEXT) = :eid
            ORDER BY cer.mention_count DESC, cer.total_views DESC
            LIMIT :lim
        """), {"eid": entity_uuid, "lim": limit}).fetchall()
    except Exception as exc:
        _log.warning("[C1] entity_creators query failed: %s", exc)
        return []

    return [
        TopCreatorRow(
            platform=r[0],
            creator_id=r[1],
            creator_handle=r[2],
            quality_tier=r[17],
            category=r[18],
            mention_count=int(r[4] or 0),
            unique_content_count=int(r[5] or 0),
            first_mention_date=_fmt_dt(r[6]) if r[6] else None,
            last_mention_date=_fmt_dt(r[7]) if r[7] else None,
            total_views=int(r[8] or 0),
            avg_views=float(r[9]) if r[9] is not None else None,
            total_likes=int(r[10] or 0),
            total_comments=int(r[11] or 0),
            avg_engagement_rate=float(r[12]) if r[12] is not None else None,
            mentions_before_first_breakout=int(r[13] or 0),
            days_before_first_breakout=int(r[14]) if r[14] is not None else None,
            influence_score=float(r[15]) if r[15] is not None else None,
            early_signal_count=int(r[16] or 0),
        )
        for r in rows
    ]


@router.get("/perfume/{id}/creators")
def get_perfume_creators(
    id: str,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db_session),
):
    """Phase C1 — Top creators who mention this perfume entity."""
    from perfume_trend_sdk.api.schemas.creators import EntityCreatorsResponse

    top_creators = _get_entity_creators(db, id, "perfume", limit)
    return EntityCreatorsResponse(entity_id=id, entity_type="perfume", top_creators=top_creators)


@router.get("/brand/{id}/creators")
def get_brand_creators(
    id: str,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db_session),
):
    """Phase C1 — Top creators who mention this brand entity."""
    from perfume_trend_sdk.api.schemas.creators import EntityCreatorsResponse

    top_creators = _get_entity_creators(db, id, "brand", limit)
    return EntityCreatorsResponse(entity_id=id, entity_type="brand", top_creators=top_creators)


@router.get("/{entity_id:path}/sources")
def get_entity_sources(
    entity_id: str,
    hours: int = Query(72, ge=1, le=720),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db_session),
):
    """Phase I1 — Top sources driving mentions for this entity (last N hours).

    Returns sources ranked by views desc, enriched with engagement metrics.
    """
    em = _get_entity_or_404(db, entity_id)
    try:
        rows = db.execute(text("""
            SELECT
                ms.platform,
                ms.source_id,
                ms.source_name,
                SUM(COALESCE(ms.views, 0))         AS total_views,
                SUM(COALESCE(ms.likes, 0))         AS total_likes,
                SUM(COALESCE(ms.comments_count,0)) AS total_comments,
                AVG(ms.engagement_rate)             AS avg_engagement_rate,
                COUNT(*)                            AS mention_count,
                MAX(em.occurred_at)                 AS last_seen
            FROM entity_mentions em
            JOIN mention_sources ms ON ms.mention_id = em.id
            WHERE em.entity_id = :eid
              AND em.occurred_at >= NOW() - INTERVAL '1 hour' * :hours
            GROUP BY ms.platform, ms.source_id, ms.source_name
            ORDER BY total_views DESC, mention_count DESC
            LIMIT :lim
        """), {"eid": str(em.id), "hours": hours, "lim": limit}).fetchall()
    except Exception as exc:
        _log.warning("[I1] sources query failed: %s", exc)
        rows = []

    return [
        {
            "platform": r[0],
            "source_id": r[1],
            "source_name": r[2],
            "total_views": int(r[3] or 0),
            "total_likes": int(r[4] or 0),
            "total_comments": int(r[5] or 0),
            "avg_engagement_rate": float(r[6]) if r[6] is not None else None,
            "mention_count": int(r[7]),
            "last_seen": r[8].isoformat() if r[8] else None,
        }
        for r in rows
    ]


@router.get("/{entity_id:path}/mentions", response_model=List[MentionRow])
def get_entity_mentions(
    entity_id: str,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db_session),
) -> List[MentionRow]:
    em = _get_entity_or_404(db, entity_id)
    rows = (
        db.query(EntityMention)
        .filter_by(entity_id=em.id)
        .order_by(EntityMention.occurred_at.desc())
        .limit(limit)
        .all()
    )
    return [
        MentionRow(
            id=str(r.id),
            entity_type=r.entity_type,
            source_platform=r.source_platform,
            source_type=r.source_type,
            source_url=r.source_url,
            author_id=r.author_id,
            author_name=r.author_name,
            mention_count=r.mention_count,
            influence_score=r.influence_score,
            sentiment=r.sentiment,
            confidence=r.confidence,
            engagement=r.engagement,
            region=r.region,
            channel=r.channel,
            occurred_at=_fmt_dt(r.occurred_at),
        )
        for r in rows
    ]


@router.get("/{entity_id:path}", response_model=EntityDetail)
def get_entity(
    entity_id: str,
    history_days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db_session),
) -> EntityDetail:
    em = _get_entity_or_404(db, entity_id)
    brand_name_map = _safe(lambda: fetch_brand_name_map(db), {}, "brand_name_map")
    brand_name = get_brand_name(em, brand_name_map)

    latest = _safe(lambda: _get_latest_snapshot(db, em.id), None, "latest_snapshot")
    history_rows = _safe(lambda: _get_history(db, em.id, days=history_days), [], "history")
    signal_rows = _safe(lambda: _get_signals(db, em.id, limit=20), [], "signals")
    mention_rows = _safe(lambda: _get_recent_mentions(db, em.id, limit=5), [], "mentions")

    history: List[SnapshotRow] = [
        SnapshotRow(
            date=r.date.isoformat(),
            mention_count=r.mention_count or 0.0,
            unique_authors=r.unique_authors or 0,
            engagement_sum=r.engagement_sum or 0.0,
            composite_market_score=r.composite_market_score or 0.0,
            weighted_signal_score=getattr(r, "weighted_signal_score", None),
            confidence_avg=r.confidence_avg,
            momentum=r.momentum,
            acceleration=r.acceleration,
            volatility=r.volatility,
            growth_rate=r.growth_rate,
            search_index=r.search_index,
            retailer_score=r.retailer_score,
            trend_state=getattr(r, "trend_state", None),  # Phase I3
        )
        for r in history_rows
    ]

    signals: List[SignalRow] = [
        SignalRow(
            entity_id=em.entity_id,
            signal_type=s.signal_type,
            detected_at=_fmt_dt(s.detected_at),
            strength=s.strength or 0.0,
            confidence=s.confidence,
            entity_type=s.entity_type,
            ticker=em.ticker,
            canonical_name=em.canonical_name,
            brand_name=brand_name,
            metadata_json=s.metadata_json,
        )
        for s in signal_rows
    ]

    recent_mentions = _build_mention_rows(mention_rows)

    # Structured summary block (Step 8C)
    summary = _build_summary(em, latest, brand_name)

    # Legacy entity + latest dicts (kept for backward compat with existing tests)
    entity_dict: Dict[str, Any] = {}
    for c in em.__table__.columns:
        val = getattr(em, c.name)
        entity_dict[c.name] = (
            str(val) if not isinstance(val, (str, int, float, bool, type(None))) else val
        )

    latest_dict = None
    if latest:
        latest_dict = {}
        for c in latest.__table__.columns:
            val = getattr(latest, c.name)
            latest_dict[c.name] = (
                str(val) if not isinstance(val, (str, int, float, bool, type(None))) else val
            )

    return EntityDetail(
        entity=entity_dict,
        latest=latest_dict,
        history=history,
        signals=signals,
        summary=summary,
        recent_mentions=recent_mentions,
    )
