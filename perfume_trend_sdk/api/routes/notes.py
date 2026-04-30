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


@router.get("/notes/{note_name}")
def get_note_detail(
    note_name: str,
    perfume_limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Detail page for a single note: perfume count, top perfumes, related accords."""
    # Perfume count
    count_rows = _safe_query(db, """
        SELECT COUNT(*) FROM resolver_perfume_notes WHERE LOWER(note_name) = LOWER(:n)
    """, {"n": note_name})
    perfume_count = int(count_rows[0][0]) if count_rows else 0

    # Top perfumes using this note (prefer tracked entities)
    perf_rows = _safe_query(db, """
        SELECT
            rp.canonical_name,
            rb.canonical_name AS brand_name,
            em.entity_id,
            em.entity_type,
            CASE WHEN em.id IS NOT NULL THEN true ELSE false END AS has_activity_today,
            rp.id AS resolver_id
        FROM resolver_perfume_notes rpn
        JOIN resolver_perfumes rp ON rp.id = rpn.resolver_perfume_id
        LEFT JOIN resolver_brands rb ON rb.id = rp.brand_id
        LEFT JOIN entity_market em ON LOWER(em.canonical_name) = LOWER(rp.canonical_name)
        WHERE LOWER(rpn.note_name) = LOWER(:n)
        ORDER BY has_activity_today DESC, rp.canonical_name
        LIMIT :lim
    """, {"n": note_name, "lim": perfume_limit})

    top_perfumes = [
        {
            "canonical_name": r[0],
            "brand_name": r[1],
            "entity_id": r[2],
            "entity_type": r[3],
            "has_activity_today": bool(r[4]),
            "resolver_id": int(r[5]) if r[5] is not None else None,
        }
        for r in perf_rows
    ]

    # Related accords — accords that co-occur most with this note
    accord_rows = _safe_query(db, """
        SELECT rpa.accord_name, COUNT(*) AS co_count
        FROM resolver_perfume_notes rpn
        JOIN resolver_perfume_accords rpa ON rpa.resolver_perfume_id = rpn.resolver_perfume_id
        WHERE LOWER(rpn.note_name) = LOWER(:n)
        GROUP BY rpa.accord_name
        ORDER BY co_count DESC
        LIMIT 15
    """, {"n": note_name})

    related_accords = [{"accord_name": r[0], "co_count": int(r[1])} for r in accord_rows]

    return {
        "note_name": note_name,
        "perfume_count": perfume_count,
        "top_perfumes": top_perfumes,
        "related_accords": related_accords,
    }


@router.get("/accords/{accord_name}")
def get_accord_detail(
    accord_name: str,
    perfume_limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Detail page for a single accord: perfume count, top perfumes, related notes."""
    count_rows = _safe_query(db, """
        SELECT COUNT(*) FROM resolver_perfume_accords WHERE LOWER(accord_name) = LOWER(:a)
    """, {"a": accord_name})
    perfume_count = int(count_rows[0][0]) if count_rows else 0

    perf_rows = _safe_query(db, """
        SELECT
            rp.canonical_name,
            rb.canonical_name AS brand_name,
            em.entity_id,
            em.entity_type,
            CASE WHEN em.id IS NOT NULL THEN true ELSE false END AS has_activity_today,
            rp.id AS resolver_id
        FROM resolver_perfume_accords rpa
        JOIN resolver_perfumes rp ON rp.id = rpa.resolver_perfume_id
        LEFT JOIN resolver_brands rb ON rb.id = rp.brand_id
        LEFT JOIN entity_market em ON LOWER(em.canonical_name) = LOWER(rp.canonical_name)
        WHERE LOWER(rpa.accord_name) = LOWER(:a)
        ORDER BY has_activity_today DESC, rp.canonical_name
        LIMIT :lim
    """, {"a": accord_name, "lim": perfume_limit})

    top_perfumes = [
        {
            "canonical_name": r[0],
            "brand_name": r[1],
            "entity_id": r[2],
            "entity_type": r[3],
            "has_activity_today": bool(r[4]),
            "resolver_id": int(r[5]) if r[5] is not None else None,
        }
        for r in perf_rows
    ]

    # Related notes — notes that co-occur most with this accord
    note_rows = _safe_query(db, """
        SELECT rpn.note_name, COUNT(*) AS co_count
        FROM resolver_perfume_accords rpa
        JOIN resolver_perfume_notes rpn ON rpn.resolver_perfume_id = rpa.resolver_perfume_id
        WHERE LOWER(rpa.accord_name) = LOWER(:a)
        GROUP BY rpn.note_name
        ORDER BY co_count DESC
        LIMIT 15
    """, {"a": accord_name})

    related_notes = [{"note_name": r[0], "co_count": int(r[1])} for r in note_rows]

    return {
        "accord_name": accord_name,
        "perfume_count": perfume_count,
        "top_perfumes": top_perfumes,
        "related_notes": related_notes,
    }
