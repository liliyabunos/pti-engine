from __future__ import annotations

"""
Entity routes — Market Terminal API v1.

GET /api/v1/entities               — list all entities with latest snapshot
GET /api/v1/entities/{entity_id}   — entity detail: summary + chart series + signals + mentions
GET /api/v1/entities/{entity_id}/mentions — raw mention drilldown
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
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
    import logging
    _log = logging.getLogger(__name__)

    def _safe(fn, fallback, label):
        try:
            return fn()
        except Exception as exc:
            _log.error("[PTI] entity query failed (%s): %s", label, exc)
            try:
                db.rollback()
            except Exception:
                pass
            return fallback

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
