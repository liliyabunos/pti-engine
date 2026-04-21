from __future__ import annotations

"""
Catalog routes — expose full resolver KB to the UI.

GET /api/v1/catalog/perfumes  — search all known perfumes (resolver_perfumes)
GET /api/v1/catalog/brands    — search all known brands (resolver_brands)
GET /api/v1/catalog/counts    — headline counts: known brands, perfumes, active today

These endpoints query resolver_* Postgres tables (migration 014) which contain the
full 56k-perfume catalog, regardless of whether each entity has market timeseries data.

Active market data (entity_market) is cross-referenced via a LEFT JOIN so callers
know which catalog entities are already tracked in the market engine.

SQLite fallback: if resolver_* tables don't exist (dev/local without Postgres),
all three endpoints return gracefully empty results instead of crashing.
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


class CatalogBrandRow(BaseModel):
    resolver_id: int
    canonical_name: str
    perfume_count: int = 0
    entity_id: Optional[str] = None


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


# ---------------------------------------------------------------------------
# GET /api/v1/catalog/perfumes
# ---------------------------------------------------------------------------

@router.get("/perfumes", response_model=CatalogPerfumesResponse)
def catalog_perfumes(
    q: Optional[str] = Query(None, description="Text search — name or brand"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("canonical_name", pattern="^(canonical_name|brand_name)$"),
    active_only: bool = Query(False, description="Return only entities that have market data"),
    db: Session = Depends(get_db_session),
) -> CatalogPerfumesResponse:
    """Return perfumes from the resolver catalog (56k+ entries).

    Results include all known perfumes regardless of ingestion activity.
    entity_id is non-null when the perfume has been resolved from content
    and has a corresponding entity_market row (navigable entity page).
    """
    if not _is_postgres(db):
        return CatalogPerfumesResponse(total=0, limit=limit, offset=offset, rows=[])

    try:
        q_pattern = f"%{q.strip()}%" if q else None

        where = ""
        if q_pattern:
            where = (
                "WHERE (LOWER(rp.canonical_name) LIKE LOWER(:q) "
                "OR LOWER(rb.canonical_name) LIKE LOWER(:q))"
            )
        active_join = "INNER JOIN" if active_only else "LEFT JOIN"

        count_sql = text(
            f"""
            SELECT COUNT(*)
            FROM resolver_perfumes rp
            LEFT JOIN resolver_brands rb ON rp.brand_id = rb.id
            {active_join} entity_market em
                ON LOWER(em.canonical_name) = LOWER(rp.canonical_name)
               AND em.entity_type = 'perfume'
            {where}
            """
        )

        order_col = "rb.canonical_name" if sort_by == "brand_name" else "rp.canonical_name"
        rows_sql = text(
            f"""
            SELECT
                rp.id               AS resolver_id,
                rp.canonical_name   AS canonical_name,
                rb.canonical_name   AS brand_name,
                em.entity_id        AS entity_id
            FROM resolver_perfumes rp
            LEFT JOIN resolver_brands rb ON rp.brand_id = rb.id
            {active_join} entity_market em
                ON LOWER(em.canonical_name) = LOWER(rp.canonical_name)
               AND em.entity_type = 'perfume'
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
    active_only: bool = Query(False, description="Return only brands with market data"),
    db: Session = Depends(get_db_session),
) -> CatalogBrandsResponse:
    """Return brands from the resolver catalog (1,600+ brands).

    Results include all known brands.
    entity_id is non-null when the brand has an entity_market row.
    """
    if not _is_postgres(db):
        return CatalogBrandsResponse(total=0, limit=limit, offset=offset, rows=[])

    try:
        q_pattern = f"%{q.strip()}%" if q else None
        where = "WHERE LOWER(rb.canonical_name) LIKE LOWER(:q)" if q_pattern else ""
        active_join = "INNER JOIN" if active_only else "LEFT JOIN"

        count_sql = text(
            f"""
            SELECT COUNT(DISTINCT rb.id)
            FROM resolver_brands rb
            {active_join} entity_market em
                ON LOWER(em.canonical_name) = LOWER(rb.canonical_name)
               AND em.entity_type = 'brand'
            {where}
            """
        )

        rows_sql = text(
            f"""
            SELECT
                rb.id                                    AS resolver_id,
                rb.canonical_name                        AS canonical_name,
                COUNT(rp.id)                             AS perfume_count,
                em.entity_id                             AS entity_id
            FROM resolver_brands rb
            LEFT JOIN resolver_perfumes rp ON rp.brand_id = rb.id
            {active_join} entity_market em
                ON LOWER(em.canonical_name) = LOWER(rb.canonical_name)
               AND em.entity_type = 'brand'
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
# GET /api/v1/catalog/counts
# ---------------------------------------------------------------------------

@router.get("/counts", response_model=CatalogCounts)
def catalog_counts(
    db: Session = Depends(get_db_session),
) -> CatalogCounts:
    """Return headline catalog counts for the dashboard/screener header.

    known_perfumes — total in resolver_perfumes (full KB)
    known_brands   — total in resolver_brands
    active_today   — entity_market rows with mention_count > 0 on the latest date
    """
    if not _is_postgres(db):
        return CatalogCounts(known_perfumes=0, known_brands=0, active_today=0)

    try:
        row = db.execute(
            text(
                """
                SELECT
                    (SELECT COUNT(*) FROM resolver_perfumes)  AS known_perfumes,
                    (SELECT COUNT(*) FROM resolver_brands)    AS known_brands,
                    (
                        SELECT COUNT(DISTINCT etd.entity_id)
                        FROM entity_timeseries_daily etd
                        WHERE etd.date = (
                            SELECT MAX(date)
                            FROM entity_timeseries_daily
                            WHERE mention_count > 0
                        )
                        AND etd.mention_count > 0
                    )                                         AS active_today
                """
            )
        ).fetchone()

        if row is None:
            return CatalogCounts(known_perfumes=0, known_brands=0, active_today=0)

        return CatalogCounts(
            known_perfumes=int(row[0]),
            known_brands=int(row[1]),
            active_today=int(row[2]),
        )

    except Exception as exc:
        _log.warning("[catalog] counts query failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return CatalogCounts(known_perfumes=0, known_brands=0, active_today=0)
