from __future__ import annotations

"""
SIG-ID1 — Admin Signal Candidates API.

GET  /api/v1/admin/signal-candidates           — list unresolved_signal_candidates
POST /api/v1/admin/signal-candidates/{id}/dismiss — set candidate_status='dismissed'

Authorization model (identical to other admin routes):
  All requests require X-Pti-Admin-User header.
  Header is injected by the Next.js server route ONLY after Supabase session
  verification against ADMIN_EMAILS / ADMIN_USER_IDS env allowlist.
  Browser cannot forge this header.

Read-only operator visibility for SIG-ID1. The operator reviews brand-qualified
phrases the resolver saw but could not match — surfaced from the previously-dead
unresolved_mentions_json layer by scripts/harvest_unresolved_brand_signals.py.
"""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from perfume_trend_sdk.api.dependencies import get_db_session

router = APIRouter()


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
# Schemas
# ---------------------------------------------------------------------------

class SignalCandidateRow(BaseModel):
    id: str
    phrase: str
    brand_token: str
    brand_canonical_name: str
    occurrence_count: int
    source_count: int
    first_seen: Optional[str]
    last_seen: Optional[str]
    candidate_status: str
    operator_notes: Optional[str]
    created_at: str
    updated_at: str


class SignalCandidatesResponse(BaseModel):
    total: int
    items: List[SignalCandidateRow]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=SignalCandidatesResponse)
def list_signal_candidates(
    status: Optional[str] = Query(None, description="Filter by candidate_status (pending|dismissed|added_to_catalog|all)"),
    min_occurrences: int = Query(1, ge=1, description="Minimum occurrence count"),
    brand: Optional[str] = Query(None, description="Filter by brand_canonical_name (case-insensitive partial match)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: str = Depends(_get_admin_user),
    db: Session = Depends(get_db_session),
) -> SignalCandidatesResponse:
    """List unresolved signal candidates for operator review."""
    filters = ["occurrence_count >= :min_occ"]
    params: dict = {"min_occ": min_occurrences, "limit": limit, "offset": offset}

    if status and status != "all":
        filters.append("candidate_status = :status")
        params["status"] = status
    elif not status:
        # Default: show pending only
        filters.append("candidate_status = 'pending'")

    if brand:
        filters.append("LOWER(brand_canonical_name) LIKE :brand")
        params["brand"] = f"%{brand.lower()}%"

    where = "WHERE " + " AND ".join(filters)

    count_sql = text(f"SELECT COUNT(*) FROM unresolved_signal_candidates {where}")
    rows_sql = text(
        f"""
        SELECT id, phrase, brand_token, brand_canonical_name,
               occurrence_count, source_count,
               first_seen, last_seen,
               candidate_status, operator_notes,
               created_at, updated_at
        FROM unresolved_signal_candidates
        {where}
        ORDER BY occurrence_count DESC, last_seen DESC
        LIMIT :limit OFFSET :offset
        """
    )

    total = db.execute(count_sql, params).scalar() or 0
    rows = db.execute(rows_sql, params).fetchall()

    items = [
        SignalCandidateRow(
            id=str(r[0]),
            phrase=r[1],
            brand_token=r[2],
            brand_canonical_name=r[3],
            occurrence_count=r[4],
            source_count=r[5],
            first_seen=str(r[6]) if r[6] else None,
            last_seen=str(r[7]) if r[7] else None,
            candidate_status=r[8],
            operator_notes=r[9],
            created_at=str(r[10]),
            updated_at=str(r[11]),
        )
        for r in rows
    ]

    return SignalCandidatesResponse(total=total, items=items)


@router.post("/{candidate_id}/dismiss")
def dismiss_signal_candidate(
    candidate_id: str,
    _admin: str = Depends(_get_admin_user),
    db: Session = Depends(get_db_session),
) -> dict:
    """Dismiss a candidate — marks as not actionable (e.g. already guarded, noise)."""
    try:
        cid = uuid.UUID(candidate_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid UUID")

    sql = text(
        """
        UPDATE unresolved_signal_candidates
        SET candidate_status = 'dismissed', updated_at = now()
        WHERE id = :id AND candidate_status = 'pending'
        RETURNING id
        """
    )
    row = db.execute(sql, {"id": str(cid)}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found or not in pending status")
    db.commit()
    return {"id": str(cid), "candidate_status": "dismissed"}
