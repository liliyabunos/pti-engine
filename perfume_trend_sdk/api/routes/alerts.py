from __future__ import annotations

"""
Alerts routes — Market Terminal API v1.

GET    /api/v1/alerts                — list all alerts
POST   /api/v1/alerts                — create alert
PATCH  /api/v1/alerts/{id}           — update alert (pause/resume/rename)
GET    /api/v1/alerts/history        — alert event history

V1 auth strategy:
  All operations use DEV_OWNER_KEY ("dev"). See watchlists.py for details.
"""

import uuid
from datetime import datetime
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from perfume_trend_sdk.api.dependencies import get_db_session
from perfume_trend_sdk.api.schemas.alerts import (
    AlertCreate,
    AlertEventRow,
    AlertHistoryResponse,
    AlertListResponse,
    AlertPatch,
    AlertRow,
)
from perfume_trend_sdk.db.market.alert import DEV_OWNER_KEY, Alert, AlertEvent
from perfume_trend_sdk.db.market.models import EntityMarket

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_dt(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _get_alert_or_404(db: Session, alert_id: str) -> Alert:
    alert = (
        db.query(Alert)
        .filter_by(id=uuid.UUID(alert_id), owner_key=DEV_OWNER_KEY)
        .first()
    )
    if alert is None:
        raise HTTPException(status_code=404, detail=f"Alert not found: {alert_id}")
    return alert


def _entity_display(db: Session, entity_id: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (canonical_name, ticker) for an entity_id string."""
    em = db.query(EntityMarket).filter_by(entity_id=entity_id).first()
    if em:
        return em.canonical_name, em.ticker
    return None, None


def _build_alert_row(alert: Alert, canonical_name: Optional[str], ticker: Optional[str]) -> AlertRow:
    return AlertRow(
        id=str(alert.id),
        name=alert.name,
        entity_id=alert.entity_id,
        entity_type=alert.entity_type,
        canonical_name=canonical_name,
        ticker=ticker,
        condition_type=alert.condition_type,
        threshold_value=alert.threshold_value,
        cooldown_hours=alert.cooldown_hours,
        is_active=alert.is_active,
        delivery_type=alert.delivery_type,
        last_triggered_at=_fmt_dt(alert.last_triggered_at) if alert.last_triggered_at else None,
        created_at=_fmt_dt(alert.created_at),
        updated_at=_fmt_dt(alert.updated_at),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=AlertListResponse)
def list_alerts(db: Session = Depends(get_db_session)):
    """Return all alerts for the dev owner, newest first."""
    alerts = (
        db.query(Alert)
        .filter_by(owner_key=DEV_OWNER_KEY)
        .order_by(Alert.created_at.desc())
        .all()
    )

    # Batch-load entity display info
    entity_ids = list({a.entity_id for a in alerts})
    em_rows = (
        db.query(EntityMarket)
        .filter(EntityMarket.entity_id.in_(entity_ids))
        .all()
    )
    em_map = {em.entity_id: em for em in em_rows}

    rows = []
    for alert in alerts:
        em = em_map.get(alert.entity_id)
        rows.append(
            _build_alert_row(
                alert,
                canonical_name=em.canonical_name if em else None,
                ticker=em.ticker if em else None,
            )
        )
    return AlertListResponse(alerts=rows)


@router.post("", response_model=AlertRow, status_code=201)
def create_alert(
    body: AlertCreate,
    db: Session = Depends(get_db_session),
):
    """Create a new entity alert."""
    # Validate entity exists
    em = db.query(EntityMarket).filter_by(entity_id=body.entity_id).first()
    if em is None:
        raise HTTPException(status_code=404, detail=f"Entity not found: {body.entity_id}")

    alert = Alert(
        id=uuid.uuid4(),
        owner_key=DEV_OWNER_KEY,
        name=body.name.strip(),
        entity_id=body.entity_id,
        entity_type=body.entity_type,
        condition_type=body.condition_type,
        threshold_value=body.threshold_value,
        cooldown_hours=body.cooldown_hours,
        is_active=True,
        delivery_type="in_app",
    )
    db.add(alert)
    db.flush()

    return _build_alert_row(alert, canonical_name=em.canonical_name, ticker=em.ticker)


@router.patch("/{alert_id}", response_model=AlertRow)
def patch_alert(
    alert_id: str,
    body: AlertPatch,
    db: Session = Depends(get_db_session),
):
    """Update alert fields: pause/resume (is_active), rename, change cooldown."""
    alert = _get_alert_or_404(db, alert_id)

    if body.is_active is not None:
        alert.is_active = body.is_active
    if body.name is not None:
        alert.name = body.name.strip()
    if body.cooldown_hours is not None:
        alert.cooldown_hours = body.cooldown_hours

    alert.updated_at = datetime.utcnow()
    db.flush()

    canonical_name, ticker = _entity_display(db, alert.entity_id)
    return _build_alert_row(alert, canonical_name=canonical_name, ticker=ticker)


@router.get("/history", response_model=AlertHistoryResponse)
def get_alert_history(
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    alert_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db_session),
):
    """Return recent alert events, newest first.

    Optionally filter by alert_id to see history for a specific alert.
    Only returns events for alerts owned by the dev owner.
    """
    # Sub-select alert IDs owned by dev
    owned_ids_q = db.query(Alert.id).filter_by(owner_key=DEV_OWNER_KEY)
    if alert_id:
        owned_ids_q = owned_ids_q.filter(Alert.id == uuid.UUID(alert_id))
    owned_ids = [r[0] for r in owned_ids_q.all()]

    if not owned_ids:
        return AlertHistoryResponse(events=[], total=0)

    base_q = (
        db.query(AlertEvent)
        .filter(AlertEvent.alert_id.in_(owned_ids))
        .order_by(AlertEvent.triggered_at.desc())
    )
    total = base_q.count()
    events = base_q.offset(offset).limit(limit).all()

    # Batch-load alert names and entity display info
    alert_ids_needed = list({ev.alert_id for ev in events})
    alerts_map = {
        a.id: a
        for a in db.query(Alert).filter(Alert.id.in_(alert_ids_needed)).all()
    }
    entity_ids_needed = list({ev.entity_id for ev in events})
    em_map = {
        em.entity_id: em
        for em in db.query(EntityMarket)
        .filter(EntityMarket.entity_id.in_(entity_ids_needed))
        .all()
    }

    rows = []
    for ev in events:
        al = alerts_map.get(ev.alert_id)
        em = em_map.get(ev.entity_id)
        rows.append(
            AlertEventRow(
                id=str(ev.id),
                alert_id=str(ev.alert_id),
                alert_name=al.name if al else None,
                entity_id=ev.entity_id,
                entity_type=ev.entity_type,
                canonical_name=em.canonical_name if em else None,
                triggered_at=_fmt_dt(ev.triggered_at),
                status=ev.status,
                reason_json=ev.reason_json,
                created_at=_fmt_dt(ev.created_at),
            )
        )
    return AlertHistoryResponse(events=rows, total=total)
