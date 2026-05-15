from __future__ import annotations

"""
FTG-3 / RI1-QA — Admin Relationship Intelligence API.

GET    /api/v1/admin/relationship-intelligence                — list all relationships
POST   /api/v1/admin/relationship-intelligence/{id}/approve  — set is_public=TRUE + operator_reviewed=TRUE
POST   /api/v1/admin/relationship-intelligence/{id}/unpublish — set is_public=FALSE
PATCH  /api/v1/admin/relationship-intelligence/{id}          — update confidence_score / relation_type

Authorization model (identical to admin_source_intake.py):
  All requests require X-Pti-Admin-User header.
  Header is injected by the Next.js server route ONLY after Supabase session
  verification against ADMIN_EMAILS / ADMIN_USER_IDS env allowlist.
  Browser cannot forge this header.

Public quality gate (FTG-3 contract — must not be relaxed):
  A relationship row is publicly displayed only when ALL of:
    is_public = TRUE
    operator_reviewed = TRUE
    confidence_score >= 0.700
"""

import uuid
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from perfume_trend_sdk.api.dependencies import get_db_session
from perfume_trend_sdk.db.market.fragrance_relationship import (
    VALID_RELATION_TYPES,
    FragranceRelationship,
)

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

class EvidenceRow(BaseModel):
    id: str
    evidence_type: str
    note: Optional[str] = None
    query_text: Optional[str] = None
    observed_date: str


class RelationshipRow(BaseModel):
    id: str
    subject_canonical_name: str
    relation_type: str
    object_canonical_name: str
    confidence_score: float
    is_public: bool
    operator_reviewed: bool
    first_observed_date: str
    last_confirmed_date: str
    evidence_summary: Optional[str] = None
    formula_version: int
    created_at: str
    evidence: List[EvidenceRow] = []


class RelationshipListResponse(BaseModel):
    total: int
    relationships: List[RelationshipRow]


class PatchRelationshipRequest(BaseModel):
    confidence_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    relation_type: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_date(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _row_to_relationship(r, evidence_rows) -> RelationshipRow:
    return RelationshipRow(
        id=str(r[0]),
        subject_canonical_name=r[1],
        relation_type=r[2],
        object_canonical_name=r[3],
        confidence_score=float(r[4]),
        is_public=bool(r[5]),
        operator_reviewed=bool(r[6]),
        first_observed_date=_fmt_date(r[7]),
        last_confirmed_date=_fmt_date(r[8]),
        evidence_summary=r[9],
        formula_version=int(r[10]),
        created_at=_fmt_date(r[11]),
        evidence=evidence_rows,
    )


def _get_evidence_for(db: Session, relationship_id: str) -> List[EvidenceRow]:
    rows = db.execute(text(
        "SELECT id, evidence_type, note, query_text, observed_date "
        "FROM relationship_evidence WHERE relationship_id = :rid "
        "ORDER BY observed_date DESC"
    ), {"rid": relationship_id}).fetchall()
    return [
        EvidenceRow(
            id=str(r[0]),
            evidence_type=r[1],
            note=r[2],
            query_text=r[3],
            observed_date=_fmt_date(r[4]),
        )
        for r in rows
    ]


def _get_relationship_or_404(db: Session, relationship_id: str):
    row = db.execute(text(
        "SELECT id, subject_canonical_name, relation_type, object_canonical_name, "
        "       confidence_score, is_public, operator_reviewed, "
        "       first_observed_date, last_confirmed_date, evidence_summary, "
        "       formula_version, created_at "
        "FROM fragrance_relationships WHERE id = :rid"
    ), {"rid": relationship_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Relationship not found: {relationship_id}")
    return row


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=RelationshipListResponse)
def list_relationships(
    filter: str = Query("all", description="all | public | non_public"),
    db: Session = Depends(get_db_session),
    admin: str = Depends(_get_admin_user),
) -> RelationshipListResponse:
    """List all fragrance relationships with optional filter."""
    valid_filters = {"all", "public", "non_public", "pending_review"}
    if filter not in valid_filters:
        raise HTTPException(status_code=422, detail=f"filter must be one of {valid_filters}")

    where = ""
    if filter == "public":
        where = "WHERE is_public = TRUE"
    elif filter == "non_public":
        where = "WHERE is_public = FALSE"
    elif filter == "pending_review":
        # FTG-4: machine-generated candidates awaiting operator decision
        where = "WHERE operator_reviewed = FALSE AND is_public = FALSE"

    rows = db.execute(text(
        "SELECT id, subject_canonical_name, relation_type, object_canonical_name, "
        "       confidence_score, is_public, operator_reviewed, "
        "       first_observed_date, last_confirmed_date, evidence_summary, "
        "       formula_version, created_at "
        f"FROM fragrance_relationships {where} "
        "ORDER BY confidence_score DESC, subject_canonical_name"
    )).fetchall()

    result = []
    for r in rows:
        ev = _get_evidence_for(db, str(r[0]))
        result.append(_row_to_relationship(r, ev))

    return RelationshipListResponse(total=len(result), relationships=result)


@router.post("/{relationship_id}/approve")
def approve_relationship(
    relationship_id: str,
    db: Session = Depends(get_db_session),
    admin: str = Depends(_get_admin_user),
) -> dict:
    """Approve a relationship for public display.

    Sets is_public=TRUE and operator_reviewed=TRUE.
    Row must already satisfy confidence_score >= 0.700 to appear in public display.
    """
    row = _get_relationship_or_404(db, relationship_id)
    db.execute(text(
        "UPDATE fragrance_relationships SET is_public = TRUE, operator_reviewed = TRUE "
        "WHERE id = :rid"
    ), {"rid": relationship_id})
    db.commit()
    return {"id": relationship_id, "is_public": True, "operator_reviewed": True}


@router.post("/{relationship_id}/unpublish")
def unpublish_relationship(
    relationship_id: str,
    db: Session = Depends(get_db_session),
    admin: str = Depends(_get_admin_user),
) -> dict:
    """Remove a relationship from public display (set is_public=FALSE).

    Does not delete the row or reset operator_reviewed.
    """
    _get_relationship_or_404(db, relationship_id)
    db.execute(text(
        "UPDATE fragrance_relationships SET is_public = FALSE WHERE id = :rid"
    ), {"rid": relationship_id})
    db.commit()
    return {"id": relationship_id, "is_public": False}


@router.patch("/{relationship_id}")
def patch_relationship(
    relationship_id: str,
    body: PatchRelationshipRequest,
    db: Session = Depends(get_db_session),
    admin: str = Depends(_get_admin_user),
) -> dict:
    """Update confidence_score and/or relation_type.

    Both fields are optional; only provided fields are updated.
    relation_type must be one of VALID_RELATION_TYPES.
    """
    _get_relationship_or_404(db, relationship_id)

    updates: list[str] = []
    params: dict = {"rid": relationship_id}

    if body.confidence_score is not None:
        updates.append("confidence_score = :confidence_score")
        params["confidence_score"] = body.confidence_score

    if body.relation_type is not None:
        if body.relation_type not in VALID_RELATION_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"relation_type must be one of {sorted(VALID_RELATION_TYPES)}",
            )
        updates.append("relation_type = :relation_type")
        params["relation_type"] = body.relation_type

    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")

    db.execute(
        text(f"UPDATE fragrance_relationships SET {', '.join(updates)} WHERE id = :rid"),
        params,
    )
    db.commit()

    # Return updated row
    row = _get_relationship_or_404(db, relationship_id)
    return {
        "id": relationship_id,
        "confidence_score": float(row[4]),
        "relation_type": row[2],
    }
