from __future__ import annotations

"""
SC1.2A — TikTok Creator Watchlist API routes.

Operator-facing endpoints (no public frontend yet).

GET  /api/v1/tiktok-watchlist              — list accounts
POST /api/v1/tiktok-watchlist              — add one account
PATCH /api/v1/tiktok-watchlist/{handle}   — change status
GET  /api/v1/tiktok-watchlist/{handle}    — get one account
GET  /api/v1/tiktok-watchlist/{handle}/audit — audit log for account
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from perfume_trend_sdk.api.dependencies import get_db_session
from perfume_trend_sdk.services import tiktok_watchlist as svc

router = APIRouter()
_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TikTokAccountIn(BaseModel):
    handle: str = Field(..., description="TikTok handle, @handle, or profile URL")
    display_name: Optional[str] = None
    category: Optional[str] = None
    tier: Optional[str] = None
    status: str = Field("pending_review", description="pending_review | active | paused | rejected | error")
    seed_source: Optional[str] = None
    source_method: str = Field("manual_seed")
    confidence: Optional[float] = None
    notes: Optional[str] = None


class StatusPatch(BaseModel):
    status: str = Field(..., description="New status")
    note: Optional[str] = None


class TikTokAccountOut(BaseModel):
    id: int
    platform: str
    platform_handle: str
    platform_url: Optional[str]
    display_name: Optional[str]
    category: Optional[str]
    tier: Optional[str]
    status: str
    seed_source: Optional[str]
    source_method: str
    confidence: Optional[float]
    follower_count: Optional[int]
    avg_views: Optional[float]
    notes: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]

    model_config = {"from_attributes": True}


class TikTokAuditRow(BaseModel):
    id: int
    platform: str
    platform_handle: str
    action: str
    old_status: Optional[str]
    new_status: Optional[str]
    source_method: Optional[str]
    note: Optional[str]
    created_at: Optional[str]


def _fmt(d: Optional[dict]) -> Optional[dict]:
    """Convert datetime fields to ISO strings for JSON serialization."""
    if d is None:
        return None
    out = dict(d)
    for k in ("created_at", "updated_at", "last_checked_at", "last_new_content_at"):
        if k in out and out[k] is not None and hasattr(out[k], "isoformat"):
            out[k] = out[k].isoformat()
    return out


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", summary="List TikTok watchlist accounts")
def list_accounts(
    status: Optional[str] = Query(None),
    source_method: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_session),
) -> dict:
    accounts = svc.list_accounts(
        db, status=status, source_method=source_method, limit=limit, offset=offset
    )
    return {"total": len(accounts), "accounts": [_fmt(a) for a in accounts]}


@router.post("", status_code=201, summary="Add TikTok creator to watchlist")
def add_account(
    body: TikTokAccountIn,
    db: Session = Depends(get_db_session),
) -> dict:
    try:
        account = svc.add_account(
            db,
            handle=body.handle,
            display_name=body.display_name,
            category=body.category,
            tier=body.tier,
            status=body.status,
            seed_source=body.seed_source,
            source_method=body.source_method,
            confidence=body.confidence,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _fmt(account)


@router.get("/{handle}", summary="Get one TikTok watchlist account")
def get_account(
    handle: str,
    db: Session = Depends(get_db_session),
) -> dict:
    try:
        normalized = svc.normalize_handle(handle)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    account = svc.get_account(db, normalized)
    if not account:
        raise HTTPException(status_code=404, detail=f"TikTok account not found: @{normalized}")
    return _fmt(account)


@router.patch("/{handle}", summary="Change status of a TikTok watchlist account")
def patch_status(
    handle: str,
    body: StatusPatch,
    db: Session = Depends(get_db_session),
) -> dict:
    try:
        normalized = svc.normalize_handle(handle)
        account = svc.change_status(db, normalized, body.status, note=body.note)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _fmt(account)


@router.get("/{handle}/audit", summary="Audit log for a TikTok watchlist account")
def get_audit(
    handle: str,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db_session),
) -> dict:
    try:
        normalized = svc.normalize_handle(handle)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    rows = db.execute(
        text("""
            SELECT id, platform, platform_handle, action,
                   old_status, new_status, source_method, note, created_at
            FROM creator_watchlist_audit_log
            WHERE platform = 'tiktok' AND platform_handle = :handle
            ORDER BY created_at DESC
            LIMIT :limit
        """),
        {"handle": normalized, "limit": limit},
    ).fetchall()

    audit = [
        {
            "id": r[0], "platform": r[1], "platform_handle": r[2],
            "action": r[3], "old_status": r[4], "new_status": r[5],
            "source_method": r[6], "note": r[7],
            "created_at": r[8].isoformat() if r[8] and hasattr(r[8], "isoformat") else str(r[8]),
        }
        for r in rows
    ]
    return {"platform_handle": normalized, "entries": audit}
