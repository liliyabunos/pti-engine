from __future__ import annotations

"""
Catalog routes — expose full resolver KB to the UI.

GET /api/v1/catalog/perfumes  — search all known perfumes (resolver_perfumes)
GET /api/v1/catalog/brands    — search all known brands (resolver_brands)
GET /api/v1/catalog/counts    — headline counts: known brands, perfumes, active today
GET /api/v1/catalog/stats     — alias for /counts (backward-compat)

These endpoints query resolver_* Postgres tables (migration 014) which contain the
full 56k-perfume catalog, regardless of whether each entity has market timeseries data.

Active market data (entity_market + entity_timeseries_daily) is cross-referenced so
callers know which catalog entries are tracked and which have activity today.

SQLite fallback: if resolver_* tables don't exist (dev/local without Postgres),
all endpoints return gracefully empty results instead of crashing.
"""

import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from perfume_trend_sdk.api.dependencies import get_db_session

_log = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class CatalogPerfumeRow(BaseModel):
    resolver_id: int
    canonical_name: str
    brand_name: Optional[str] = None
    # entity_id is the slug-string used in /entities/<entity_id> URLs.
    # Present if this perfume has been resolved from real ingested content and
    # has a row in entity_market; None for catalog-only entries.
    entity_id: Optional[str] = None
    # True when this entity has mention_count > 0 on the latest data date.
    has_activity_today: bool = False


class CatalogBrandRow(BaseModel):
    resolver_id: int
    canonical_name: str
    perfume_count: int = 0
    entity_id: Optional[str] = None
    has_activity_today: bool = False


class CatalogPerfumesResponse(BaseModel):
    total: int
    limit: int
    offset: int
    rows: List[CatalogPerfumeRow]


class CatalogBrandsResponse(BaseModel):
    total: int
    limit: int
    offset: int
    rows: List[CatalogBrandRow]


class CatalogCounts(BaseModel):
    known_perfumes: int
    known_brands: int
    # active_today = entities with mention_count > 0 on the latest data date
    active_today: int
    # tracked = entities in entity_market (ever resolved from content)
    tracked_perfumes: int = 0
    tracked_brands: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_postgres(_db: Session) -> bool:
    """Return True when the active database is PostgreSQL.

    Checks DATABASE_URL rather than the session's bind dialect (deprecated
    in SQLAlchemy 2.x). resolver_* tables only exist in Postgres; SQLite
    dev environments gracefully return empty results.
    """
    db_url = os.environ.get("DATABASE_URL", "")
    return db_url.startswith("postgresql") or db_url.startswith("postgres")


# CTE that materialises entity UUIDs active on the latest data date.
# Used by both /perfumes and /brands to set has_activity_today.
_ACTIVE_TODAY_CTE = """
WITH active_today AS (
    SELECT entity_id
    FROM   entity_timeseries_daily
    WHERE  date = (
               SELECT MAX(date)
               FROM   entity_timeseries_daily
               WHERE  mention_count > 0
           )
    AND    mention_count > 0
)
"""


# ---------------------------------------------------------------------------
# GET /api/v1/catalog/perfumes
# ---------------------------------------------------------------------------

@router.get("/perfumes", response_model=CatalogPerfumesResponse)
def catalog_perfumes(
    q: Optional[str] = Query(None, description="Text search — name or brand"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("canonical_name", pattern="^(canonical_name|brand_name)$"),
    active_only: bool = Query(False, description="Return only entities with activity today"),
    db: Session = Depends(get_db_session),
) -> CatalogPerfumesResponse:
    """Return perfumes from the resolver catalog (56k+ entries).

    Results include all known perfumes regardless of ingestion activity.
    entity_id is non-null when the perfume has been resolved from content.
    has_activity_today is true when mention_count > 0 on the latest data date.
    active_only=true filters to only entities with activity today.
    """
    if not _is_postgres(db):
        return CatalogPerfumesResponse(total=0, limit=limit, offset=offset, rows=[])

    try:
        q_pattern = f"%{q.strip()}%" if q else None

        where_clauses = []
        if q_pattern:
            where_clauses.append(
                "(LOWER(rp.canonical_name) LIKE LOWER(:q) "
                "OR LOWER(rb.canonical_name) LIKE LOWER(:q))"
            )
        if active_only:
            where_clauses.append("at.entity_id IS NOT NULL")

        where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        order_col = "rb.canonical_name" if sort_by == "brand_name" else "rp.canonical_name"

        count_sql = text(
            f"""
            {_ACTIVE_TODAY_CTE}
            SELECT COUNT(*)
            FROM   resolver_perfumes rp
            LEFT JOIN resolver_brands     rb ON rp.brand_id = rb.id
            LEFT JOIN entity_market       em ON LOWER(em.canonical_name) = LOWER(rp.canonical_name)
                                            AND em.entity_type = 'perfume'
            LEFT JOIN active_today        at ON at.entity_id = em.id
            {where}
            """
        )

        rows_sql = text(
            f"""
            {_ACTIVE_TODAY_CTE}
            SELECT
                rp.id                                AS resolver_id,
                rp.canonical_name                    AS canonical_name,
                rb.canonical_name                    AS brand_name,
                em.entity_id                         AS entity_id,
                (at.entity_id IS NOT NULL)           AS has_activity_today
            FROM   resolver_perfumes rp
            LEFT JOIN resolver_brands     rb ON rp.brand_id = rb.id
            LEFT JOIN entity_market       em ON LOWER(em.canonical_name) = LOWER(rp.canonical_name)
                                            AND em.entity_type = 'perfume'
            LEFT JOIN active_today        at ON at.entity_id = em.id
            {where}
            ORDER BY {order_col} NULLS LAST
            LIMIT :limit OFFSET :offset
            """
        )

        params: dict = {"limit": limit, "offset": offset}
        if q_pattern:
            params["q"] = q_pattern

        total_row = db.execute(count_sql, params).fetchone()
        total = int(total_row[0]) if total_row else 0

        data_rows = db.execute(rows_sql, params).fetchall()
        rows = [
            CatalogPerfumeRow(
                resolver_id=int(r[0]),
                canonical_name=r[1],
                brand_name=r[2],
                entity_id=r[3],
                has_activity_today=bool(r[4]),
            )
            for r in data_rows
        ]
        return CatalogPerfumesResponse(total=total, limit=limit, offset=offset, rows=rows)

    except Exception as exc:
        _log.warning("[catalog] perfumes query failed (resolver_* tables may not exist): %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return CatalogPerfumesResponse(total=0, limit=limit, offset=offset, rows=[])


# ---------------------------------------------------------------------------
# GET /api/v1/catalog/brands
# ---------------------------------------------------------------------------

@router.get("/brands", response_model=CatalogBrandsResponse)
def catalog_brands(
    q: Optional[str] = Query(None, description="Text search on brand name"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    active_only: bool = Query(False, description="Return only brands with activity today"),
    db: Session = Depends(get_db_session),
) -> CatalogBrandsResponse:
    """Return brands from the resolver catalog (1,600+ brands).

    Results include all known brands regardless of ingestion activity.
    has_activity_today is true when the brand's entity_market row has
    mention_count > 0 on the latest data date.
    """
    if not _is_postgres(db):
        return CatalogBrandsResponse(total=0, limit=limit, offset=offset, rows=[])

    try:
        q_pattern = f"%{q.strip()}%" if q else None

        where_clauses = []
        if q_pattern:
            where_clauses.append("LOWER(rb.canonical_name) LIKE LOWER(:q)")
        if active_only:
            where_clauses.append("at.entity_id IS NOT NULL")

        where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        count_sql = text(
            f"""
            {_ACTIVE_TODAY_CTE}
            SELECT COUNT(DISTINCT rb.id)
            FROM   resolver_brands        rb
            LEFT JOIN resolver_perfumes   rp ON rp.brand_id = rb.id
            LEFT JOIN entity_market       em ON LOWER(em.canonical_name) = LOWER(rb.canonical_name)
                                            AND em.entity_type = 'brand'
            LEFT JOIN active_today        at ON at.entity_id = em.id
            {where}
            """
        )

        rows_sql = text(
            f"""
            {_ACTIVE_TODAY_CTE}
            SELECT
                rb.id                                AS resolver_id,
                rb.canonical_name                    AS canonical_name,
                COUNT(rp.id)                         AS perfume_count,
                em.entity_id                         AS entity_id,
                BOOL_OR(at.entity_id IS NOT NULL)    AS has_activity_today
            FROM   resolver_brands        rb
            LEFT JOIN resolver_perfumes   rp ON rp.brand_id = rb.id
            LEFT JOIN entity_market       em ON LOWER(em.canonical_name) = LOWER(rb.canonical_name)
                                            AND em.entity_type = 'brand'
            LEFT JOIN active_today        at ON at.entity_id = em.id
            {where}
            GROUP BY rb.id, rb.canonical_name, em.entity_id
            ORDER BY rb.canonical_name
            LIMIT :limit OFFSET :offset
            """
        )

        params: dict = {"limit": limit, "offset": offset}
        if q_pattern:
            params["q"] = q_pattern

        total_row = db.execute(count_sql, params).fetchone()
        total = int(total_row[0]) if total_row else 0

        data_rows = db.execute(rows_sql, params).fetchall()
        rows = [
            CatalogBrandRow(
                resolver_id=int(r[0]),
                canonical_name=r[1],
                perfume_count=int(r[2]),
                entity_id=r[3],
                has_activity_today=bool(r[4]) if r[4] is not None else False,
            )
            for r in data_rows
        ]
        return CatalogBrandsResponse(total=total, limit=limit, offset=offset, rows=rows)

    except Exception as exc:
        _log.warning("[catalog] brands query failed (resolver_* tables may not exist): %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return CatalogBrandsResponse(total=0, limit=limit, offset=offset, rows=[])


# ---------------------------------------------------------------------------
# GET /api/v1/catalog/counts  (also aliased as /stats)
# ---------------------------------------------------------------------------

def _build_counts(db: Session) -> CatalogCounts:
    row = db.execute(
        text(
            """
            SELECT
                (SELECT COUNT(*) FROM resolver_perfumes)                             AS known_perfumes,
                (SELECT COUNT(*) FROM resolver_brands)                               AS known_brands,
                (
                    SELECT COUNT(DISTINCT etd.entity_id)
                    FROM   entity_timeseries_daily etd
                    WHERE  etd.date = (
                               SELECT MAX(date)
                               FROM   entity_timeseries_daily
                               WHERE  mention_count > 0
                           )
                    AND    etd.mention_count > 0
                )                                                                    AS active_today,
                (
                    SELECT COUNT(*) FROM entity_market WHERE entity_type = 'perfume'
                )                                                                    AS tracked_perfumes,
                (
                    SELECT COUNT(*) FROM entity_market WHERE entity_type = 'brand'
                )                                                                    AS tracked_brands
            """
        )
    ).fetchone()

    if row is None:
        return CatalogCounts(known_perfumes=0, known_brands=0, active_today=0)

    return CatalogCounts(
        known_perfumes=int(row[0]),
        known_brands=int(row[1]),
        active_today=int(row[2]),
        tracked_perfumes=int(row[3]),
        tracked_brands=int(row[4]),
    )


@router.get("/counts", response_model=CatalogCounts)
def catalog_counts(
    db: Session = Depends(get_db_session),
) -> CatalogCounts:
    """Return headline catalog counts for the dashboard/screener header.

    known_perfumes    — total in resolver_perfumes (full KB, 56k+)
    known_brands      — total in resolver_brands (1,600+)
    active_today      — entities with mention_count > 0 on the latest data date
    tracked_perfumes  — entity_market rows with entity_type='perfume'
    tracked_brands    — entity_market rows with entity_type='brand'
    """
    if not _is_postgres(db):
        return CatalogCounts(known_perfumes=0, known_brands=0, active_today=0)

    try:
        return _build_counts(db)
    except Exception as exc:
        _log.warning("[catalog] counts query failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return CatalogCounts(known_perfumes=0, known_brands=0, active_today=0)


@router.get("/stats", response_model=CatalogCounts)
def catalog_stats(
    db: Session = Depends(get_db_session),
) -> CatalogCounts:
    """Alias for /counts — same response shape."""
    return catalog_counts(db=db)
