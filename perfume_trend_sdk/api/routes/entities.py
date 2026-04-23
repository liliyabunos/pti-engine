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


def _get_recent_mentions(db: Session, entity_uuid, limit: int = 5) -> List[EntityMention]:
    return (
        db.query(EntityMention)
        .filter_by(entity_id=entity_uuid)
        .order_by(EntityMention.occurred_at.desc())
        .limit(limit)
        .all()
    )


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
    has_activity_today: bool = False
    aliases_count: int = 0
    # Market metrics — None for catalog_only
    latest_score: Optional[float] = None
    latest_growth: Optional[float] = None
    latest_signal: Optional[str] = None
    latest_date: Optional[str] = None
    confidence_avg: Optional[float] = None
    momentum: Optional[float] = None
    # Time series + events
    timeseries: List[SnapshotRow] = []
    recent_signals: List[SignalRow] = []
    recent_mentions: List[RecentMentionRow] = []
    # Enrichment
    notes_top: List[str] = []
    notes_middle: List[str] = []
    notes_base: List[str] = []
    accords: List[str] = []
    notes_source: Optional[str] = None   # "fragrantica" | "parfumo"
    similar_perfumes: List[SimilarPerfumeRow] = []


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
    # Linked perfumes — catalog_perfumes: all from resolver (up to 100)
    # top_perfumes kept for backward compat (same data as catalog_perfumes)
    catalog_perfumes: List[BrandPerfumeRow] = []
    top_perfumes: List[BrandPerfumeRow] = []   # alias: same list
    timeseries: List[SnapshotRow] = []
    recent_signals: List[SignalRow] = []
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
            CASE WHEN etd.mention_count > 0 THEN true ELSE false END AS has_activity_today
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
            confidence_avg=r.confidence_avg,
            momentum=r.momentum,
            acceleration=r.acceleration,
            volatility=r.volatility,
            growth_rate=r.growth_rate,
            search_index=r.search_index,
            retailer_score=r.retailer_score,
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
    return [
        RecentMentionRow(
            source_platform=m.source_platform,
            source_url=m.source_url,
            author_name=m.author_name or m.author_id,
            engagement=m.engagement,
            occurred_at=_fmt_dt(m.occurred_at),
        )
        for m in mention_rows
    ]


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
        latest_sig = signal_rows[0].signal_type if signal_rows else None

        return PerfumeEntityDetail(
            id=em.entity_id,
            resolver_id=resolver_id,
            canonical_name=em.canonical_name,
            brand_name=em.brand_name,
            ticker=em.ticker,
            state=state,
            has_activity_today=has_activity,
            aliases_count=aliases,
            latest_score=latest.composite_market_score if latest else None,
            latest_growth=latest.growth_rate if latest else None,
            latest_signal=latest_sig,
            latest_date=latest.date.isoformat() if latest and latest.date else None,
            confidence_avg=latest.confidence_avg if latest else None,
            momentum=latest.momentum if latest else None,
            timeseries=_build_snapshot_rows(history_rows),
            recent_signals=_build_signal_rows(signal_rows, em, em.brand_name),
            recent_mentions=_build_mention_rows(mention_rows),
            notes_top=notes_top,
            notes_middle=notes_mid,
            notes_base=notes_base,
            accords=accords,
            notes_source=notes_source,
            similar_perfumes=similar,
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
    return PerfumeEntityDetail(
        id=str(resolver_id),
        resolver_id=resolver_id,
        canonical_name=rp_row[1],
        brand_name=rp_row[2],
        state="catalog_only",
        aliases_count=aliases,
        notes_top=cat_top,
        notes_middle=cat_mid,
        notes_base=cat_base,
        accords=cat_acc,
        notes_source=cat_source,
        similar_perfumes=similar,
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
            catalog_perfumes=catalog_perfumes,
            top_perfumes=catalog_perfumes,
            timeseries=_build_snapshot_rows(history_rows),
            recent_signals=_build_signal_rows(signal_rows, em, None),
            top_notes=top_notes,
            top_accords=top_accords,
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
            confidence_avg=r.confidence_avg,
            momentum=r.momentum,
            acceleration=r.acceleration,
            volatility=r.volatility,
            growth_rate=r.growth_rate,
            search_index=r.search_index,
            retailer_score=r.retailer_score,
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

    recent_mentions: List[RecentMentionRow] = [
        RecentMentionRow(
            source_platform=m.source_platform,
            source_url=m.source_url,
            author_name=m.author_name or m.author_id,
            engagement=m.engagement,
            occurred_at=_fmt_dt(m.occurred_at),
        )
        for m in mention_rows
    ]

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
