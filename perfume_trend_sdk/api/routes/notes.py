from __future__ import annotations

"""
Notes and Accords routes — Market Terminal API v1.

GET /api/v1/notes/top     — top notes by frequency across all KB perfumes
GET /api/v1/accords/top   — top accords by frequency
GET /api/v1/notes/search  — note name substring search (autocomplete)
"""

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from perfume_trend_sdk.api.dependencies import get_db_session

router = APIRouter()
_log = logging.getLogger(__name__)


def _safe_query(db: Session, sql: str, params: Dict[str, Any]) -> List:
    try:
        return db.execute(text(sql), params).fetchall()
    except Exception as exc:
        _log.warning("[notes] query failed: %s", exc)
        return []


@router.get("/notes/top")
def get_top_notes(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    rows = _safe_query(db, """
        SELECT note_name, COUNT(*) AS perfume_count
        FROM resolver_perfume_notes
        GROUP BY note_name
        ORDER BY perfume_count DESC
        LIMIT :lim
    """, {"lim": limit})
    return [{"note_name": r[0], "perfume_count": int(r[1])} for r in rows]


@router.get("/accords/top")
def get_top_accords(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    rows = _safe_query(db, """
        SELECT accord_name, COUNT(*) AS perfume_count
        FROM resolver_perfume_accords
        GROUP BY accord_name
        ORDER BY perfume_count DESC
        LIMIT :lim
    """, {"lim": limit})
    return [{"accord_name": r[0], "perfume_count": int(r[1])} for r in rows]


@router.get("/notes/search")
def search_notes(
    q: str = Query("", description="Note name substring for autocomplete"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    if not q.strip():
        return []
    rows = _safe_query(db, """
        SELECT DISTINCT note_name
        FROM resolver_perfume_notes
        WHERE note_name ILIKE :q
        ORDER BY note_name
        LIMIT :lim
    """, {"q": f"%{q.strip()}%", "lim": limit})
    return [{"note_name": r[0]} for r in rows]
