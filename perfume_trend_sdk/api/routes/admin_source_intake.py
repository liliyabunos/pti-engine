from __future__ import annotations

"""
SOURCE-INTAKE-V1A — Admin Source Intake API.

GET    /api/v1/admin/source-intake/batches                     — list batches
POST   /api/v1/admin/source-intake/batches                     — create batch (used by CLI --persist)
GET    /api/v1/admin/source-intake/batches/{batch_id}          — batch + candidates
GET    /api/v1/admin/source-intake/candidates/{candidate_id}   — candidate detail
PATCH  /api/v1/admin/source-intake/candidates/{candidate_id}   — edit override URL / notes
POST   /api/v1/admin/source-intake/candidates/{candidate_id}/approve
POST   /api/v1/admin/source-intake/candidates/{candidate_id}/reject
POST   /api/v1/admin/source-intake/candidates/{candidate_id}/defer
POST   /api/v1/admin/source-intake/candidates/{candidate_id}/mark-duplicate
POST   /api/v1/admin/source-intake/candidates/{candidate_id}/rerun
POST   /api/v1/admin/source-intake/batches/{batch_id}/apply
POST   /api/v1/admin/source-intake/batches/{batch_id}/production-verify

Authorization model (identical to admin_creator_claims.py):
  - All requests require X-Pti-Admin-User header.
  - Header is injected by the Next.js server route ONLY after Supabase session
    verification against ADMIN_EMAILS / ADMIN_USER_IDS env allowlist.
  - Browser cannot forge this header.

Safety rules:
  - NEEDS_OPERATOR_REVIEW / DEFERRED cannot be applied directly.
  - Only VERIFIED_ADD_READY and OPERATOR_APPROVED are apply-eligible.
  - Apply uses ON CONFLICT (channel_id) DO NOTHING — idempotent.
  - Apply never triggers ingestion; the next pipeline run picks up new channels.
  - Audit log is append-only — no deletes or updates.
  - resolved_platform_id must be a canonical ID (not a search URL) for apply.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import requests as _requests
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from perfume_trend_sdk.api.dependencies import get_db_session
from perfume_trend_sdk.api.schemas.source_intake import (
    APPLY_ELIGIBLE_STATUSES,
    CANDIDATE_STATUSES,
    TERMINAL_STATUSES,
    ApplyResult,
    BatchListResponse,
    BatchSummary,
    CandidateListResponse,
    CandidatePersistItem,
    CandidateRow,
    PersistBatchRequest,
    ProductionVerifyResult,
    RejectRequest,
    UpdateCandidateRequest,
)

router = APIRouter()
_log = logging.getLogger(__name__)

_VALID_STATUS_FILTERS = CANDIDATE_STATUSES | {"all"}
_YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
_YT_API_BASE = "https://www.googleapis.com/youtube/v3"


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

def _get_admin_user(
    x_pti_admin_user: Optional[str] = Header(None),
) -> str:
    if not x_pti_admin_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return x_pti_admin_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(val) -> Optional[str]:
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


def _row_to_candidate(r) -> CandidateRow:
    return CandidateRow(
        id=str(r[0]),
        batch_id=str(r[1]),
        platform=r[2],
        candidate_name=r[3],
        input_url=r[4],
        resolved_platform_id=r[5],
        resolved_title=r[6],
        subscriber_count=r[7],
        total_content_count=r[8],
        recent_content_count=r[9],
        recent_titles_sample=r[10],
        resolve_method=r[11],
        confidence=r[12],
        status=r[13],
        decision_reason=r[14],
        operator_override_url=r[15],
        operator_notes=r[16],
        quality_tier=r[17],
        reviewed_by=r[18],
        reviewed_at=_fmt(r[19]),
        applied_at=_fmt(r[20]),
        apply_error=r[21],
        created_at=_fmt(r[22]),
    )


_CANDIDATE_COLS = """
    id, batch_id, platform, candidate_name, input_url,
    resolved_platform_id, resolved_title, subscriber_count,
    total_content_count, recent_content_count, recent_titles_sample,
    resolve_method, confidence, status, decision_reason,
    operator_override_url, operator_notes, quality_tier,
    reviewed_by, reviewed_at, applied_at, apply_error, created_at
"""


def _write_audit(
    db: Session,
    candidate_id: str,
    actor: str,
    action: str,
    old_status: Optional[str],
    new_status: str,
    notes: Optional[str] = None,
) -> None:
    db.execute(text("""
        INSERT INTO source_intake_audit_log
            (id, candidate_id, actor, action, old_status, new_status, notes, created_at)
        VALUES
            (:id, :candidate_id, :actor, :action, :old_status, :new_status, :notes, :created_at)
    """), {
        "id": str(uuid.uuid4()),
        "candidate_id": candidate_id,
        "actor": actor,
        "action": action,
        "old_status": old_status,
        "new_status": new_status,
        "notes": notes,
        "created_at": datetime.now(timezone.utc),
    })


def _get_candidate_or_404(db: Session, candidate_id: str):
    row = db.execute(text(f"""
        SELECT {_CANDIDATE_COLS} FROM source_intake_candidates WHERE id = :id
    """), {"id": candidate_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return row


def _assert_not_terminal(row) -> None:
    status = row[13]
    if status in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Candidate is in terminal status '{status}' and cannot be modified",
        )


# ---------------------------------------------------------------------------
# YouTube re-verification helper (used by /rerun endpoint)
# ---------------------------------------------------------------------------

def _rerun_youtube(override_url: str, api_key: str) -> dict:
    """
    Given an operator-supplied URL/handle, attempt to resolve to a YouTube channel.
    Returns a dict with resolved fields and new status.
    """
    url = override_url.strip()
    channel_id = None
    title = None
    subscriber_count = None
    video_count = None
    handle = None
    recent_count = 0
    recent_titles: list = []
    resolve_method = "handle"
    confidence = "high"
    new_status = "NEEDS_OPERATOR_REVIEW"
    reason = "Could not resolve to a channel_id"

    # Extract handle from URL variants
    raw_handle = None
    if "youtube.com/@" in url:
        raw_handle = url.split("youtube.com/@")[-1].split("/")[0].split("?")[0]
    elif url.startswith("@"):
        raw_handle = url.lstrip("@")
    elif "youtube.com/channel/UC" in url:
        channel_id = url.split("youtube.com/channel/")[-1].split("/")[0].split("?")[0]
        resolve_method = "direct_id"
    elif url.startswith("UC") and len(url) == 24:
        channel_id = url
        resolve_method = "direct_id"

    try:
        if channel_id:
            # Direct channel ID — just fetch metadata
            resp = _requests.get(
                f"{_YT_API_BASE}/channels",
                params={"part": "snippet,statistics,contentDetails", "id": channel_id, "key": api_key},
                timeout=10,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
            if items:
                item = items[0]
                title = item["snippet"]["title"]
                handle = item["snippet"].get("customUrl", "")
                subscriber_count = int(item["statistics"].get("subscriberCount", 0))
                video_count = int(item["statistics"].get("videoCount", 0))
                uploads_pid = item["contentDetails"]["relatedPlaylists"]["uploads"]
                # Check activity
                act = _requests.get(
                    f"{_YT_API_BASE}/playlistItems",
                    params={"part": "snippet", "playlistId": uploads_pid, "maxResults": 15, "key": api_key},
                    timeout=10,
                )
                if act.ok:
                    now = datetime.now(timezone.utc)
                    for item2 in act.json().get("items", []):
                        pub = item2["snippet"].get("publishedAt", "")
                        try:
                            from datetime import timedelta
                            dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                            if (now - dt).days <= 30:
                                recent_count += 1
                                t = item2["snippet"].get("title", "")
                                if t:
                                    recent_titles.append(t)
                        except Exception:
                            pass
        elif raw_handle:
            resp = _requests.get(
                f"{_YT_API_BASE}/channels",
                params={"part": "snippet,statistics,contentDetails", "forHandle": raw_handle, "key": api_key},
                timeout=10,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
            if items:
                item = items[0]
                channel_id = item["id"]
                title = item["snippet"]["title"]
                handle = item["snippet"].get("customUrl", f"@{raw_handle}")
                subscriber_count = int(item["statistics"].get("subscriberCount", 0))
                video_count = int(item["statistics"].get("videoCount", 0))
                uploads_pid = item["contentDetails"]["relatedPlaylists"]["uploads"]
                act = _requests.get(
                    f"{_YT_API_BASE}/playlistItems",
                    params={"part": "snippet", "playlistId": uploads_pid, "maxResults": 15, "key": api_key},
                    timeout=10,
                )
                if act.ok:
                    now = datetime.now(timezone.utc)
                    for item2 in act.json().get("items", []):
                        pub = item2["snippet"].get("publishedAt", "")
                        try:
                            from datetime import timedelta
                            dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                            if (now - dt).days <= 30:
                                recent_count += 1
                                t = item2["snippet"].get("title", "")
                                if t:
                                    recent_titles.append(t)
                        except Exception:
                            pass
    except Exception as exc:
        _log.warning("[source-intake] rerun youtube fetch error: %s", exc)
        return {
            "resolved_platform_id": None,
            "resolved_title": None,
            "subscriber_count": None,
            "total_content_count": None,
            "recent_content_count": 0,
            "recent_titles_sample": None,
            "resolve_method": resolve_method,
            "confidence": "low",
            "status": "NEEDS_OPERATOR_REVIEW",
            "decision_reason": f"API error during rerun: {exc}",
        }

    if not channel_id:
        return {
            "resolved_platform_id": None,
            "resolved_title": None,
            "subscriber_count": None,
            "total_content_count": None,
            "recent_content_count": 0,
            "recent_titles_sample": None,
            "resolve_method": resolve_method,
            "confidence": "low",
            "status": "NEEDS_OPERATOR_REVIEW",
            "decision_reason": reason,
        }

    if recent_count == 0:
        new_status = "SKIP_INACTIVE"
        reason = "No videos published in last 30 days"
    else:
        new_status = "VERIFIED_ADD_READY"
        reason = f"{recent_count} video(s) in last 30 days"

    return {
        "resolved_platform_id": channel_id,
        "resolved_title": title,
        "subscriber_count": subscriber_count,
        "total_content_count": video_count,
        "recent_content_count": recent_count,
        "recent_titles_sample": json.dumps(recent_titles[:3]) if recent_titles else None,
        "resolve_method": resolve_method,
        "confidence": confidence,
        "status": new_status,
        "decision_reason": reason,
    }


# ---------------------------------------------------------------------------
# Tier helper (mirrors verify script)
# ---------------------------------------------------------------------------

def _assign_tier(subscriber_count: Optional[int]) -> str:
    if not subscriber_count:
        return "tier_4"
    if subscriber_count >= 500_000:
        return "tier_1"
    if subscriber_count >= 50_000:
        return "tier_2"
    if subscriber_count >= 10_000:
        return "tier_3"
    return "tier_4"


# ---------------------------------------------------------------------------
# GET /batches — list batches
# ---------------------------------------------------------------------------

@router.get("/batches", response_model=BatchListResponse, summary="Admin: list source intake batches")
def list_batches(
    platform: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    admin_user: str = Depends(_get_admin_user),
    db: Session = Depends(get_db_session),
) -> BatchListResponse:
    where = []
    params: dict = {"limit": min(limit, 200), "offset": offset}
    if platform:
        where.append("b.platform = :platform")
        params["platform"] = platform
    if status:
        where.append("b.status = :status")
        params["status"] = status
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    try:
        rows = db.execute(text(f"""
            SELECT
                b.id, b.batch_label, b.platform, b.description, b.status,
                b.candidate_count, b.applied_count, b.created_at, b.created_by,
                b.applied_at, b.applied_by, b.verified_at,
                COUNT(CASE WHEN c.status = 'VERIFIED_ADD_READY' THEN 1 END) AS cnt_add_ready,
                COUNT(CASE WHEN c.status = 'NEEDS_OPERATOR_REVIEW' THEN 1 END) AS cnt_review,
                COUNT(CASE WHEN c.status = 'APPLIED' THEN 1 END) AS cnt_applied,
                COUNT(CASE WHEN c.status = 'OPERATOR_APPROVED' THEN 1 END) AS cnt_approved
            FROM source_intake_batches b
            LEFT JOIN source_intake_candidates c ON c.batch_id = b.id
            {where_sql}
            GROUP BY b.id, b.batch_label, b.platform, b.description, b.status,
                     b.candidate_count, b.applied_count, b.created_at, b.created_by,
                     b.applied_at, b.applied_by, b.verified_at
            ORDER BY b.created_at DESC
            LIMIT :limit OFFSET :offset
        """), params).fetchall()

        count_row = db.execute(text(f"""
            SELECT COUNT(*) FROM source_intake_batches b {where_sql}
        """), {k: v for k, v in params.items() if k not in ("limit", "offset")}).fetchone()
    except Exception as exc:
        _log.error("[source-intake] list_batches failed: %s", exc)
        raise HTTPException(status_code=503, detail="Source intake service unavailable")

    batches = [
        BatchSummary(
            id=str(r[0]), batch_label=r[1], platform=r[2], description=r[3],
            status=r[4], candidate_count=r[5], applied_count=r[6],
            created_at=_fmt(r[7]), created_by=r[8],
            applied_at=_fmt(r[9]), applied_by=r[10], verified_at=_fmt(r[11]),
            count_verified_add_ready=r[12] or 0,
            count_needs_review=r[13] or 0,
            count_applied=r[14] or 0,
            count_operator_approved=r[15] or 0,
        )
        for r in rows
    ]
    return BatchListResponse(batches=batches, total=count_row[0] if count_row else 0)


# ---------------------------------------------------------------------------
# POST /batches — create batch + candidates (used by CLI --persist)
# ---------------------------------------------------------------------------

@router.post("/batches", summary="Admin: create source intake batch", status_code=201)
def create_batch(
    body: PersistBatchRequest,
    admin_user: str = Depends(_get_admin_user),
    db: Session = Depends(get_db_session),
) -> dict:
    batch_id = str(uuid.uuid4())
    try:
        db.execute(text("""
            INSERT INTO source_intake_batches
                (id, batch_label, platform, description, status, candidate_count, applied_count,
                 created_at, created_by)
            VALUES
                (:id, :batch_label, :platform, :description, 'open', :candidate_count, 0,
                 :created_at, :created_by)
        """), {
            "id": batch_id,
            "batch_label": body.batch_label,
            "platform": body.platform,
            "description": body.description,
            "candidate_count": len(body.candidates),
            "created_by": body.created_by,
            "created_at": datetime.now(timezone.utc),
        })

        for c in body.candidates:
            cid = str(uuid.uuid4())
            db.execute(text("""
                INSERT INTO source_intake_candidates
                    (id, batch_id, platform, candidate_name, input_url,
                     resolved_platform_id, resolved_title, subscriber_count,
                     total_content_count, recent_content_count, recent_titles_sample,
                     resolve_method, confidence, status, decision_reason, quality_tier,
                     created_at)
                VALUES
                    (:id, :batch_id, :platform, :candidate_name, :input_url,
                     :resolved_platform_id, :resolved_title, :subscriber_count,
                     :total_content_count, :recent_content_count, :recent_titles_sample,
                     :resolve_method, :confidence, :status, :decision_reason, :quality_tier,
                     :created_at)
            """), {
                "id": cid,
                "batch_id": batch_id,
                "platform": body.platform,
                "candidate_name": c.candidate_name,
                "input_url": c.input_url,
                "resolved_platform_id": c.resolved_platform_id,
                "resolved_title": c.resolved_title,
                "subscriber_count": c.subscriber_count,
                "total_content_count": c.total_content_count,
                "recent_content_count": c.recent_content_count,
                "recent_titles_sample": c.recent_titles_sample,
                "resolve_method": c.resolve_method,
                "confidence": c.confidence,
                "status": c.status,
                "decision_reason": c.decision_reason,
                "quality_tier": c.quality_tier,
                "created_at": datetime.now(timezone.utc),
            })
            _write_audit(db, cid, body.created_by, "verify", None, c.status, c.decision_reason)

        db.commit()
    except Exception as exc:
        db.rollback()
        _log.error("[source-intake] create_batch failed: %s", exc)
        raise HTTPException(status_code=503, detail="Failed to persist batch")

    _log.info("[source-intake] batch created id=%s label=%s candidates=%d by=%s",
              batch_id, body.batch_label, len(body.candidates), admin_user)
    return {"batch_id": batch_id, "candidate_count": len(body.candidates)}


# ---------------------------------------------------------------------------
# GET /batches/{batch_id} — batch detail + candidates
# ---------------------------------------------------------------------------

@router.get("/batches/{batch_id}", response_model=CandidateListResponse,
            summary="Admin: list candidates for a batch")
def list_candidates(
    batch_id: str,
    status: Optional[str] = Query(None),
    limit: int = 200,
    offset: int = 0,
    admin_user: str = Depends(_get_admin_user),
    db: Session = Depends(get_db_session),
) -> CandidateListResponse:
    if status and status != "all" and status not in CANDIDATE_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"status must be one of: {', '.join(sorted(CANDIDATE_STATUSES))} | all",
        )

    # Verify batch exists
    batch = db.execute(text("SELECT id FROM source_intake_batches WHERE id = :id"),
                       {"id": batch_id}).fetchone()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    where = ["c.batch_id = :batch_id"]
    params: dict = {"batch_id": batch_id, "limit": min(limit, 500), "offset": offset}
    if status and status != "all":
        where.append("c.status = :status")
        params["status"] = status

    where_sql = "WHERE " + " AND ".join(where)

    try:
        rows = db.execute(text(f"""
            SELECT {_CANDIDATE_COLS}
            FROM source_intake_candidates c
            {where_sql}
            ORDER BY c.created_at ASC
            LIMIT :limit OFFSET :offset
        """), params).fetchall()

        count_row = db.execute(text(f"""
            SELECT COUNT(*) FROM source_intake_candidates c {where_sql}
        """), {k: v for k, v in params.items() if k not in ("limit", "offset")}).fetchone()
    except Exception as exc:
        _log.error("[source-intake] list_candidates failed: %s", exc)
        raise HTTPException(status_code=503, detail="Source intake service unavailable")

    return CandidateListResponse(
        candidates=[_row_to_candidate(r) for r in rows],
        total=count_row[0] if count_row else 0,
        batch_id=batch_id,
    )


# ---------------------------------------------------------------------------
# GET /candidates/{candidate_id} — candidate detail
# ---------------------------------------------------------------------------

@router.get("/candidates/{candidate_id}", response_model=CandidateRow,
            summary="Admin: candidate detail")
def get_candidate(
    candidate_id: str,
    admin_user: str = Depends(_get_admin_user),
    db: Session = Depends(get_db_session),
) -> CandidateRow:
    row = _get_candidate_or_404(db, candidate_id)
    return _row_to_candidate(row)


# ---------------------------------------------------------------------------
# PATCH /candidates/{candidate_id} — edit override URL / notes
# ---------------------------------------------------------------------------

@router.patch("/candidates/{candidate_id}", summary="Admin: update candidate override URL or notes")
def update_candidate(
    candidate_id: str,
    body: UpdateCandidateRequest,
    admin_user: str = Depends(_get_admin_user),
    db: Session = Depends(get_db_session),
) -> dict:
    row = _get_candidate_or_404(db, candidate_id)
    _assert_not_terminal(row)

    sets = []
    params: dict = {"id": candidate_id}
    if body.operator_override_url is not None:
        sets.append("operator_override_url = :override_url")
        params["override_url"] = body.operator_override_url.strip() or None
    if body.operator_notes is not None:
        sets.append("operator_notes = :operator_notes")
        params["operator_notes"] = body.operator_notes.strip() or None

    if not sets:
        return {"candidate_id": candidate_id, "updated": False}

    try:
        db.execute(text(f"UPDATE source_intake_candidates SET {', '.join(sets)} WHERE id = :id"), params)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Update failed")

    return {"candidate_id": candidate_id, "updated": True}


# ---------------------------------------------------------------------------
# POST /candidates/{candidate_id}/approve
# ---------------------------------------------------------------------------

@router.post("/candidates/{candidate_id}/approve", summary="Admin: approve candidate")
def approve_candidate(
    candidate_id: str,
    admin_user: str = Depends(_get_admin_user),
    db: Session = Depends(get_db_session),
) -> dict:
    row = _get_candidate_or_404(db, candidate_id)
    old_status = row[13]
    _assert_not_terminal(row)
    if old_status in ("APPLIED", "APPLY_FAILED", "PRODUCTION_VERIFIED"):
        raise HTTPException(status_code=409, detail=f"Cannot approve candidate in status '{old_status}'")

    now = datetime.now(timezone.utc)
    try:
        db.execute(text("""
            UPDATE source_intake_candidates
            SET status = 'OPERATOR_APPROVED', reviewed_by = :admin, reviewed_at = :now
            WHERE id = :id
        """), {"id": candidate_id, "admin": admin_user, "now": now})
        _write_audit(db, candidate_id, admin_user, "approve", old_status, "OPERATOR_APPROVED")
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Approve failed")

    _log.info("[source-intake] candidate approved id=%s by=%s", candidate_id, admin_user)
    return {"candidate_id": candidate_id, "status": "OPERATOR_APPROVED", "reviewed_by": admin_user}


# ---------------------------------------------------------------------------
# POST /candidates/{candidate_id}/reject
# ---------------------------------------------------------------------------

@router.post("/candidates/{candidate_id}/reject", summary="Admin: reject candidate")
def reject_candidate(
    candidate_id: str,
    body: RejectRequest,
    admin_user: str = Depends(_get_admin_user),
    db: Session = Depends(get_db_session),
) -> dict:
    row = _get_candidate_or_404(db, candidate_id)
    old_status = row[13]
    _assert_not_terminal(row)

    now = datetime.now(timezone.utc)
    try:
        db.execute(text("""
            UPDATE source_intake_candidates
            SET status = 'OPERATOR_REJECTED', reviewed_by = :admin, reviewed_at = :now,
                decision_reason = :reason
            WHERE id = :id
        """), {"id": candidate_id, "admin": admin_user, "now": now, "reason": body.reason})
        _write_audit(db, candidate_id, admin_user, "reject", old_status, "OPERATOR_REJECTED", body.reason)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Reject failed")

    _log.info("[source-intake] candidate rejected id=%s by=%s", candidate_id, admin_user)
    return {"candidate_id": candidate_id, "status": "OPERATOR_REJECTED", "reviewed_by": admin_user}


# ---------------------------------------------------------------------------
# POST /candidates/{candidate_id}/defer
# ---------------------------------------------------------------------------

@router.post("/candidates/{candidate_id}/defer", summary="Admin: defer candidate review")
def defer_candidate(
    candidate_id: str,
    admin_user: str = Depends(_get_admin_user),
    db: Session = Depends(get_db_session),
) -> dict:
    row = _get_candidate_or_404(db, candidate_id)
    old_status = row[13]
    _assert_not_terminal(row)

    try:
        db.execute(text("""
            UPDATE source_intake_candidates SET status = 'DEFERRED', reviewed_by = :admin
            WHERE id = :id
        """), {"id": candidate_id, "admin": admin_user})
        _write_audit(db, candidate_id, admin_user, "defer", old_status, "DEFERRED")
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Defer failed")

    return {"candidate_id": candidate_id, "status": "DEFERRED"}


# ---------------------------------------------------------------------------
# POST /candidates/{candidate_id}/mark-duplicate
# ---------------------------------------------------------------------------

@router.post("/candidates/{candidate_id}/mark-duplicate", summary="Admin: mark candidate as duplicate")
def mark_duplicate(
    candidate_id: str,
    admin_user: str = Depends(_get_admin_user),
    db: Session = Depends(get_db_session),
) -> dict:
    row = _get_candidate_or_404(db, candidate_id)
    old_status = row[13]
    _assert_not_terminal(row)

    now = datetime.now(timezone.utc)
    try:
        db.execute(text("""
            UPDATE source_intake_candidates
            SET status = 'SKIP_DUPLICATE', reviewed_by = :admin, reviewed_at = :now,
                decision_reason = 'Manually marked as duplicate by operator'
            WHERE id = :id
        """), {"id": candidate_id, "admin": admin_user, "now": now})
        _write_audit(db, candidate_id, admin_user, "mark_duplicate", old_status, "SKIP_DUPLICATE")
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Mark duplicate failed")

    return {"candidate_id": candidate_id, "status": "SKIP_DUPLICATE"}


# ---------------------------------------------------------------------------
# POST /candidates/{candidate_id}/rerun
# ---------------------------------------------------------------------------

@router.post("/candidates/{candidate_id}/rerun", summary="Admin: rerun verification for candidate")
def rerun_candidate(
    candidate_id: str,
    admin_user: str = Depends(_get_admin_user),
    db: Session = Depends(get_db_session),
) -> dict:
    """
    Re-runs YouTube API verification using operator_override_url (required).
    Only valid for candidates in NEEDS_OPERATOR_REVIEW or DEFERRED.
    Makes live YouTube API calls — quota: ~101 units per rerun (handle) or ~102 (search).
    """
    row = _get_candidate_or_404(db, candidate_id)
    old_status = row[13]
    platform = row[2]
    override_url = row[15]  # operator_override_url

    if old_status not in ("NEEDS_OPERATOR_REVIEW", "DEFERRED", "APPLY_FAILED"):
        raise HTTPException(
            status_code=409,
            detail=f"Rerun only allowed for NEEDS_OPERATOR_REVIEW / DEFERRED / APPLY_FAILED candidates, not '{old_status}'",
        )
    if not override_url:
        raise HTTPException(
            status_code=422,
            detail="operator_override_url must be set before rerun",
        )
    if platform != "youtube":
        raise HTTPException(
            status_code=422,
            detail=f"Rerun not supported for platform '{platform}' in v1",
        )

    api_key = _YOUTUBE_API_KEY or os.environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="YOUTUBE_API_KEY not configured on server")

    result = _rerun_youtube(override_url, api_key)
    new_status = result["status"]
    now = datetime.now(timezone.utc)

    # Also check if already in youtube_channels (dedup)
    if result.get("resolved_platform_id"):
        existing = db.execute(text("""
            SELECT channel_id FROM youtube_channels WHERE channel_id = :cid
        """), {"cid": result["resolved_platform_id"]}).fetchone()
        if existing:
            new_status = "SKIP_DUPLICATE"
            result["decision_reason"] = f"channel_id {result['resolved_platform_id']} already in youtube_channels"
            result["status"] = new_status

    try:
        db.execute(text("""
            UPDATE source_intake_candidates
            SET resolved_platform_id = :resolved_platform_id,
                resolved_title = :resolved_title,
                subscriber_count = :subscriber_count,
                total_content_count = :total_content_count,
                recent_content_count = :recent_content_count,
                recent_titles_sample = :recent_titles_sample,
                resolve_method = :resolve_method,
                confidence = :confidence,
                status = :status,
                decision_reason = :decision_reason,
                quality_tier = :quality_tier,
                reviewed_by = :admin,
                reviewed_at = :now
            WHERE id = :id
        """), {
            "id": candidate_id,
            "resolved_platform_id": result.get("resolved_platform_id"),
            "resolved_title": result.get("resolved_title"),
            "subscriber_count": result.get("subscriber_count"),
            "total_content_count": result.get("total_content_count"),
            "recent_content_count": result.get("recent_content_count") or 0,
            "recent_titles_sample": result.get("recent_titles_sample"),
            "resolve_method": result.get("resolve_method"),
            "confidence": result.get("confidence"),
            "status": new_status,
            "decision_reason": result.get("decision_reason"),
            "quality_tier": _assign_tier(result.get("subscriber_count")),
            "admin": admin_user,
            "now": now,
        })
        _write_audit(db, candidate_id, admin_user, "rerun", old_status, new_status,
                     result.get("decision_reason"))
        db.commit()
    except Exception as exc:
        db.rollback()
        _log.error("[source-intake] rerun db update failed: %s", exc)
        raise HTTPException(status_code=503, detail="Rerun result save failed")

    _log.info("[source-intake] rerun id=%s old=%s new=%s by=%s", candidate_id, old_status, new_status, admin_user)
    return {
        "candidate_id": candidate_id,
        "old_status": old_status,
        "new_status": new_status,
        "resolved_platform_id": result.get("resolved_platform_id"),
        "resolved_title": result.get("resolved_title"),
        "subscriber_count": result.get("subscriber_count"),
        "recent_content_count": result.get("recent_content_count"),
        "decision_reason": result.get("decision_reason"),
    }


# ---------------------------------------------------------------------------
# POST /batches/{batch_id}/apply
# ---------------------------------------------------------------------------

@router.post("/batches/{batch_id}/apply", response_model=ApplyResult,
             summary="Admin: apply approved/add-ready candidates to youtube_channels")
def apply_batch(
    batch_id: str,
    admin_user: str = Depends(_get_admin_user),
    db: Session = Depends(get_db_session),
) -> ApplyResult:
    """
    Inserts VERIFIED_ADD_READY and OPERATOR_APPROVED candidates into youtube_channels.

    Safety:
    - Only canonical resolved_platform_id (UC...) are applied — no search URLs.
    - ON CONFLICT (channel_id) DO NOTHING — idempotent.
    - Never triggers ingestion — next pipeline run picks up new channels.
    - NEEDS_OPERATOR_REVIEW and DEFERRED are explicitly excluded.
    """
    batch = db.execute(text("SELECT id, batch_label FROM source_intake_batches WHERE id = :id"),
                       {"id": batch_id}).fetchone()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    batch_label = batch[1]

    # Load eligible candidates
    try:
        rows = db.execute(text(f"""
            SELECT {_CANDIDATE_COLS}
            FROM source_intake_candidates
            WHERE batch_id = :batch_id
              AND status IN ('VERIFIED_ADD_READY', 'OPERATOR_APPROVED')
        """), {"batch_id": batch_id}).fetchall()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Failed to load candidates")

    inserted = 0
    skipped = 0
    failed = 0
    details = []
    now = datetime.now(timezone.utc)

    _TIER_PRIORITY = {"tier_1": "high", "tier_2": "high", "tier_3": "medium", "tier_4": "low"}

    for row in rows:
        c = _row_to_candidate(row)

        # Guard: must have canonical channel_id
        if not c.resolved_platform_id or not c.resolved_platform_id.startswith("UC"):
            _log.warning("[source-intake] apply skip — no canonical channel_id: %s", c.id)
            details.append({"candidate_id": c.id, "name": c.candidate_name,
                             "result": "skipped", "reason": "no canonical channel_id"})
            skipped += 1
            continue

        cid = c.resolved_platform_id
        uploads_pid = "UU" + cid[2:]
        tier = c.quality_tier or "tier_3"
        priority = _TIER_PRIORITY.get(tier, "medium")
        notes = f"source_intake:{batch_label} | {c.candidate_name} | {c.decision_reason or ''}"

        try:
            result = db.execute(text("""
                INSERT INTO youtube_channels (
                    id, channel_id, handle, channel_url, title, normalized_title,
                    quality_tier, category, status, priority, subscriber_count, video_count,
                    uploads_playlist_id, added_at, added_by, notes
                ) VALUES (
                    :id, :channel_id, :handle, :channel_url, :title, :norm_title,
                    :quality_tier, :category, :status, :priority, :subscriber_count, :video_count,
                    :uploads_playlist_id, :added_at, :added_by, :notes
                )
                ON CONFLICT (channel_id) DO NOTHING
            """), {
                "id": str(uuid.uuid4()),
                "channel_id": cid,
                "handle": None,
                "channel_url": f"https://www.youtube.com/channel/{cid}",
                "title": c.resolved_title or c.candidate_name,
                "norm_title": (c.resolved_title or c.candidate_name).lower(),
                "quality_tier": tier,
                "category": "beauty",
                "status": "active",
                "priority": priority,
                "subscriber_count": c.subscriber_count,
                "video_count": c.total_content_count,
                "uploads_playlist_id": uploads_pid,
                "added_at": now,
                "added_by": f"source_intake:{batch_label}",
                "notes": notes,
            })
            rows_affected = result.rowcount
            if rows_affected == 1:
                inserted += 1
                new_status = "APPLIED"
                reason = "Inserted into youtube_channels"
                details.append({"candidate_id": c.id, "channel_id": cid,
                                 "name": c.candidate_name, "result": "inserted"})
            else:
                skipped += 1
                new_status = "SKIP_DUPLICATE"
                reason = "Already in youtube_channels (ON CONFLICT)"
                details.append({"candidate_id": c.id, "channel_id": cid,
                                 "name": c.candidate_name, "result": "already_exists"})

            db.execute(text("""
                UPDATE source_intake_candidates
                SET status = :status, applied_at = :now, reviewed_by = :admin
                WHERE id = :id
            """), {"status": new_status, "now": now, "admin": admin_user, "id": c.id})
            _write_audit(db, c.id, admin_user, "apply", c.status, new_status, reason)

        except Exception as exc:
            _log.error("[source-intake] apply failed for candidate=%s: %s", c.id, exc)
            failed += 1
            details.append({"candidate_id": c.id, "name": c.candidate_name,
                             "result": "failed", "error": str(exc)})
            try:
                db.execute(text("""
                    UPDATE source_intake_candidates
                    SET status = 'APPLY_FAILED', apply_error = :error WHERE id = :id
                """), {"error": str(exc), "id": c.id})
                _write_audit(db, c.id, admin_user, "apply", c.status, "APPLY_FAILED", str(exc))
            except Exception:
                pass

    try:
        db.execute(text("""
            UPDATE source_intake_batches
            SET applied_count = :applied_count, applied_at = :now, applied_by = :admin,
                status = CASE WHEN status = 'open' THEN 'applied' ELSE status END
            WHERE id = :batch_id
        """), {"applied_count": inserted, "now": now, "admin": admin_user, "batch_id": batch_id})
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Apply committed with errors in batch update")

    _log.info("[source-intake] batch applied id=%s inserted=%d skipped=%d failed=%d by=%s",
              batch_id, inserted, skipped, failed, admin_user)
    return ApplyResult(batch_id=batch_id, applied=inserted, skipped=skipped, failed=failed, details=details)


# ---------------------------------------------------------------------------
# POST /batches/{batch_id}/production-verify
# ---------------------------------------------------------------------------

@router.post("/batches/{batch_id}/production-verify", response_model=ProductionVerifyResult,
             summary="Admin: verify APPLIED candidates have content ingested")
def production_verify(
    batch_id: str,
    admin_user: str = Depends(_get_admin_user),
    db: Session = Depends(get_db_session),
) -> ProductionVerifyResult:
    """
    Checks APPLIED candidates to confirm they are in youtube_channels and have ingested content.
    Non-destructive read-only check on youtube_channels and canonical_content_items.
    Updates status to PRODUCTION_VERIFIED when ingestion is confirmed.
    """
    batch = db.execute(text("SELECT id FROM source_intake_batches WHERE id = :id"),
                       {"id": batch_id}).fetchone()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    try:
        rows = db.execute(text(f"""
            SELECT {_CANDIDATE_COLS}
            FROM source_intake_candidates
            WHERE batch_id = :batch_id AND status = 'APPLIED'
        """), {"batch_id": batch_id}).fetchall()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Failed to load applied candidates")

    verified = 0
    pending = 0
    details = []
    now = datetime.now(timezone.utc)

    for row in rows:
        c = _row_to_candidate(row)
        if not c.resolved_platform_id:
            continue

        # Check youtube_channels presence
        in_registry = db.execute(text("""
            SELECT channel_id FROM youtube_channels WHERE channel_id = :cid
        """), {"cid": c.resolved_platform_id}).fetchone()

        # Check content items
        content_count = db.execute(text("""
            SELECT COUNT(*) FROM canonical_content_items
            WHERE source_account_id = :cid AND source_platform = 'youtube'
        """), {"cid": c.resolved_platform_id}).fetchone()
        item_count = content_count[0] if content_count else 0

        if in_registry and item_count > 0:
            verified += 1
            details.append({"candidate_id": c.id, "channel_id": c.resolved_platform_id,
                             "name": c.candidate_name, "content_items": item_count,
                             "result": "production_verified"})
            try:
                db.execute(text("""
                    UPDATE source_intake_candidates SET status = 'PRODUCTION_VERIFIED' WHERE id = :id
                """), {"id": c.id})
                _write_audit(db, c.id, admin_user, "production_verify", "APPLIED",
                             "PRODUCTION_VERIFIED", f"{item_count} content items found")
            except Exception:
                pass
        else:
            pending += 1
            details.append({"candidate_id": c.id, "channel_id": c.resolved_platform_id,
                             "name": c.candidate_name, "content_items": item_count,
                             "in_registry": bool(in_registry),
                             "result": "pending_ingestion"})

    if verified > 0:
        try:
            db.execute(text("""
                UPDATE source_intake_batches SET verified_at = :now,
                    status = CASE WHEN :pending = 0 THEN 'production_verified' ELSE status END
                WHERE id = :batch_id
            """), {"now": now, "pending": pending, "batch_id": batch_id})
            db.commit()
        except Exception:
            db.rollback()

    _log.info("[source-intake] production_verify batch=%s verified=%d pending=%d by=%s",
              batch_id, verified, pending, admin_user)
    return ProductionVerifyResult(batch_id=batch_id, verified=verified,
                                  pending_ingestion=pending, details=details)
