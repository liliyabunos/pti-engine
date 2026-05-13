from __future__ import annotations

"""
Public entity routes — no authentication required.

GET /api/v1/public/perfumes/{slug}     — public perfume page data (M0 fields only)
GET /api/v1/public/brands/{slug}       — public brand page data (M0 fields only)
GET /api/v1/public/sitemap/perfumes    — slug list for sitemap generation
GET /api/v1/public/sitemap/brands      — slug list for sitemap generation

Slug contract (no DB migration required):

  Perfume: entity_market.entity_id = canonical_name verbatim (e.g. 'Creed Aventus').
           Public slug = LOWER(REGEXP_REPLACE(entity_id, '[^a-zA-Z0-9]+', '-', 'g'))
           i.e.  'Creed Aventus' → 'creed-aventus'
           Lookup: PostgreSQL functional filter (SQLite Python fallback for dev).

  Brand:   entity_market.entity_id = 'brand-{slugified}' (e.g. 'brand-creed').
           Public slug = entity_id.removeprefix('brand-') = 'creed'.
           Lookup: entity_id = f'brand-{slug}' — direct, no functional lookup needed.

Public routes must never require auth. 404 on missing entity (not redirect to login).
Only entities with market data (mention_count > 0) are publicly routable —
anti-thin-content rule from SEO_ARCHITECTURE.md §6.1.
"""

import json
import logging
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from perfume_trend_sdk.api.dependencies import get_db_session
from perfume_trend_sdk.analysis.topic_intelligence.entity_role import (
    classify_entity_role,
    get_dupe_profile,
)
from perfume_trend_sdk.db.market.models import EntityMarket

router = APIRouter()
_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Slug helpers — must be consistent across all callers
# ---------------------------------------------------------------------------

def _slugify_canonical(name: str) -> str:
    """
    Compute URL-safe slug from entity canonical name (= entity_id for perfumes).

    Rule: replace every run of non-alphanumeric characters with a single '-',
    then lowercase, then strip leading/trailing '-'.

    This exactly mirrors the PostgreSQL lookup expression:
        LOWER(REGEXP_REPLACE(entity_id, '[^a-zA-Z0-9]+', '-', 'g'))

    Examples:
        'Creed Aventus'              → 'creed-aventus'
        'Maison Francis Kurkdjian Baccarat Rouge 540'
                                     → 'maison-francis-kurkdjian-baccarat-rouge-540'
        'Dior Sauvage'               → 'dior-sauvage'
    """
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name)
    return s.lower().strip("-")


def _find_perfume_by_slug(db: Session, slug: str) -> Optional[EntityMarket]:
    """
    Find a perfume entity by its public URL slug.

    Primary path (PostgreSQL): functional WHERE clause using REGEXP_REPLACE.
    Fallback (SQLite dev): Python-side slugification scan.
    """
    try:
        row = db.execute(text("""
            SELECT id FROM entity_market
            WHERE entity_type = 'perfume'
              AND LOWER(REGEXP_REPLACE(entity_id, '[^a-zA-Z0-9]+', '-', 'g')) = :slug
            LIMIT 1
        """), {"slug": slug}).fetchone()
        if row:
            return db.query(EntityMarket).filter(EntityMarket.id == row[0]).first()
        return None
    except Exception:
        # SQLite fallback for local dev (REGEXP_REPLACE not available)
        entities = db.query(EntityMarket).filter(
            EntityMarket.entity_type == "perfume"
        ).all()
        return next(
            (e for e in entities if _slugify_canonical(e.entity_id) == slug),
            None,
        )


def _brand_slug_from_entity_id(entity_id: str) -> str:
    """Strip 'brand-' prefix from brand entity_id to get the public slug."""
    if entity_id.startswith("brand-"):
        return entity_id[len("brand-"):]
    return entity_id


# ---------------------------------------------------------------------------
# Response schemas — only M0-approved public fields
# ---------------------------------------------------------------------------

class PublicPerfumeRow(BaseModel):
    """Brief perfume row for brand page — top 5 SKUs."""
    slug: str           # URL-safe slug for /perfumes/[slug]
    canonical_name: str
    latest_score: Optional[float] = None
    trend_state: Optional[str] = None


class PublicPerfumeDetail(BaseModel):
    slug: str           # URL-safe slug for /perfumes/[slug]
    canonical_name: str
    brand_name: Optional[str] = None
    brand_slug: Optional[str] = None   # for linking to /brands/[slug]
    entity_role: str = "unknown"
    reference_original: Optional[str] = None  # dupe context (M0 approved)
    # Notes & accords
    notes_top: List[str] = []
    notes_middle: List[str] = []
    notes_base: List[str] = []
    accords: List[str] = []
    # Market data — single current-state values only (chart is gated)
    latest_score: Optional[float] = None
    trend_state: Optional[str] = None  # "rising" | "stable" | "declining" | None
    # Trend context — top 1 opportunity label only (no evidence, no confidence)
    top_opportunity: Optional[str] = None
    # Top 2 differentiators (uniqueness signals)
    top_2_differentiators: List[str] = []
    # Top 3 creator display names only (plain text — NOT links to terminal routes)
    top_3_creator_names: List[str] = []


class PublicBrandDetail(BaseModel):
    slug: str           # URL-safe slug for /brands/[slug]
    canonical_name: str
    latest_score: Optional[float] = None
    trend_state: Optional[str] = None
    perfume_count: int = 0
    top_5_perfumes: List[PublicPerfumeRow] = []


class SitemapPerfumeEntry(BaseModel):
    slug: str
    canonical_name: str
    brand_name: Optional[str] = None


class SitemapBrandEntry(BaseModel):
    slug: str
    canonical_name: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe(fn, fallback, label: str = ""):
    try:
        return fn()
    except Exception as exc:
        _log.warning("[public] %s failed: %s", label or "query", exc)
        return fallback


def _has_data(db: Session, entity_uuid) -> bool:
    """Anti-thin-content gate: entity must have at least one mention_count > 0 row."""
    row = _safe(lambda: db.execute(text("""
        SELECT 1 FROM entity_timeseries_daily
        WHERE entity_id = :eid AND mention_count > 0 LIMIT 1
    """), {"eid": str(entity_uuid)}).fetchone(), None, "has_data")
    return row is not None


def _get_latest_score_and_trend(
    db: Session, entity_uuid
) -> tuple[Optional[float], Optional[str]]:
    row = _safe(lambda: db.execute(text("""
        SELECT composite_market_score, trend_state
        FROM entity_timeseries_daily
        WHERE entity_id = :eid AND mention_count > 0
        ORDER BY date DESC LIMIT 1
    """), {"eid": str(entity_uuid)}).fetchone(), None, "latest_snap")
    if not row:
        return None, None
    return (float(row[0]) if row[0] is not None else None), row[1]


def _get_fragrantica_notes(db: Session, entity_id_slug: str):
    row = _safe(lambda: db.execute(text("""
        SELECT fr.notes_top_json, fr.notes_middle_json, fr.notes_base_json, fr.accords_json
        FROM fragrantica_records fr
        JOIN perfumes p ON CAST(p.id AS TEXT) = fr.perfume_id
        WHERE p.slug = :slug LIMIT 1
    """), {"slug": entity_id_slug}).fetchone(), None, "fragrantica_notes")
    if not row:
        return [], [], [], []
    safe_j = lambda x: json.loads(x or "[]")
    return (
        _safe(lambda: safe_j(row[0]), [], "notes_top"),
        _safe(lambda: safe_j(row[1]), [], "notes_mid"),
        _safe(lambda: safe_j(row[2]), [], "notes_base"),
        _safe(lambda: safe_j(row[3]), [], "accords"),
    )


def _get_resolver_notes(db: Session, resolver_id: Optional[int]):
    if not resolver_id:
        return [], [], [], []
    notes_rows = _safe(lambda: db.execute(text("""
        SELECT note_name, position FROM resolver_perfume_notes
        WHERE resolver_perfume_id = :rid ORDER BY position, note_name
    """), {"rid": resolver_id}).fetchall(), None, "resolver_notes")
    accords_rows = _safe(lambda: db.execute(text("""
        SELECT accord_name FROM resolver_perfume_accords
        WHERE resolver_perfume_id = :rid ORDER BY accord_name
    """), {"rid": resolver_id}).fetchall(), None, "resolver_accords")
    if notes_rows is None and accords_rows is None:
        return [], [], [], []
    top = [r[0] for r in (notes_rows or []) if r[1] == "top"]
    mid = [r[0] for r in (notes_rows or []) if r[1] == "middle"]
    base = [r[0] for r in (notes_rows or []) if r[1] == "base"]
    acc = [r[0] for r in (accords_rows or [])]
    return top, mid, base, acc


def _get_perfume_notes(db: Session, entity_id: str, resolver_id: Optional[int]):
    """entity_id here is the perfume's entity_id (= canonical name) used for fragrantica slug lookup."""
    top, mid, base, acc = _get_fragrantica_notes(db, entity_id)
    if top or mid or base or acc:
        return top, mid, base, acc
    return _get_resolver_notes(db, resolver_id)


def _get_public_semantic(
    db: Session, entity_uuid_str: str, entity_role: str
) -> tuple[list[str], list[str]]:
    """Return (differentiators[:2], opportunities[:1]) for the public page."""
    from perfume_trend_sdk.analysis.topic_intelligence.semantic import classify_entity_topics
    from perfume_trend_sdk.analysis.topic_intelligence.market_intelligence import (
        generate_market_intelligence,
    )
    try:
        rows = db.execute(text("""
            SELECT topic_type, topic_text, COUNT(*) AS occ,
                   COALESCE(AVG(source_score), 0) AS avg_score
            FROM entity_topic_links WHERE entity_id = :eid
            GROUP BY topic_type, topic_text ORDER BY occ DESC, avg_score DESC
        """), {"eid": entity_uuid_str}).fetchall()
    except Exception as exc:
        _log.warning("[public] entity_topics failed: %s", exc)
        return [], []

    raw = [(r[0], r[1], int(r[2]), float(r[3])) for r in rows]
    profile = classify_entity_topics(raw, entity_role=entity_role)
    differentiators = profile.differentiators[:2]

    try:
        intel = generate_market_intelligence(
            canonical_name="",
            differentiators=profile.differentiators,
            positioning=profile.positioning,
            intents=profile.intents,
            raw_queries=[],
            resolved_competitors=[],
            trend_state=None,
            entity_role=entity_role,
        )
        opportunities = intel.opportunities[:1] if intel and intel.opportunities else []
    except Exception as exc:
        _log.warning("[public] market_intelligence failed: %s", exc)
        opportunities = []

    return differentiators, opportunities


def _get_top_creator_names(db: Session, entity_uuid_str: str, limit: int = 3) -> List[str]:
    """
    Return top creator display names for the public page.
    Plain strings only — NOT linked to terminal /creators/* routes.
    creator_score_eligible IS NOT FALSE ensures only leaderboard-eligible creators.
    """
    rows = _safe(lambda: db.execute(text("""
        SELECT COALESCE(yc.title, cs.creator_handle) AS display_name
        FROM creator_entity_relationships cer
        JOIN creator_scores cs
          ON cs.creator_id = cer.creator_id AND cs.platform = cer.platform
        LEFT JOIN youtube_channels yc ON yc.channel_id = cer.creator_id
        WHERE cer.entity_id = :eid
          AND cs.creator_score_eligible IS NOT FALSE
        ORDER BY cs.influence_score DESC
        LIMIT :lim
    """), {"eid": entity_uuid_str, "lim": limit}).fetchall(), [], "top_creators")
    return [r[0] for r in rows if r[0]]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/perfumes/{slug}", response_model=PublicPerfumeDetail)
def get_public_perfume(slug: str, db: Session = Depends(get_db_session)) -> PublicPerfumeDetail:
    """
    Public perfume page data — M0-approved fields only, no auth required.

    Slug: URL-safe form of canonical_name (= entity_id).
      e.g. slug='creed-aventus' ← entity_id='Creed Aventus'

    Returns 404 for:
      - entities not found by slug (no match or wrong type)
      - entities with no market data (anti-thin-content rule, SEO_ARCHITECTURE.md §6.1)
    """
    em = _find_perfume_by_slug(db, slug)
    if not em or not _has_data(db, em.id):
        raise HTTPException(status_code=404, detail=f"Perfume not found: {slug}")

    latest_score, trend_state = _get_latest_score_and_trend(db, em.id)

    # Entity role + dupe context
    entity_role = classify_entity_role(em.brand_name, em.canonical_name)
    dupe = get_dupe_profile(em.brand_name, em.canonical_name)
    reference_original = dupe.reference_original if dupe else None

    # Notes & accords — entity_id = canonical_name, used as slug for fragrantica join
    resolver_id_row = _safe(lambda: db.execute(text(
        "SELECT id FROM resolver_perfumes WHERE LOWER(canonical_name) = LOWER(:n) LIMIT 1"
    ), {"n": em.canonical_name}).fetchone(), None, "resolver_id")
    resolver_id = int(resolver_id_row[0]) if resolver_id_row else None
    notes_top, notes_mid, notes_base, accords = _get_perfume_notes(
        db, em.entity_id, resolver_id
    )

    # Semantic signals (differentiators + opportunities)
    differentiators, opportunities = _get_public_semantic(db, str(em.id), entity_role)
    top_opportunity = opportunities[0] if opportunities else None

    # Top 3 creator names — plain text only, no links to terminal routes
    top_3_creator_names = _get_top_creator_names(db, str(em.id))

    # Brand slug (for /brands/[slug] link on the public page)
    brand_slug: Optional[str] = None
    if em.brand_name:
        brand_row = _safe(lambda: db.execute(text("""
            SELECT entity_id FROM entity_market
            WHERE entity_type = 'brand' AND LOWER(canonical_name) = LOWER(:n) LIMIT 1
        """), {"n": em.brand_name}).fetchone(), None, "brand_entity_id")
        if brand_row:
            brand_slug = _brand_slug_from_entity_id(brand_row[0])

    return PublicPerfumeDetail(
        slug=slug,                               # the slug that resolved this entity
        canonical_name=em.canonical_name,
        brand_name=em.brand_name,
        brand_slug=brand_slug,
        entity_role=entity_role,
        reference_original=reference_original,
        notes_top=notes_top,
        notes_middle=notes_mid,
        notes_base=notes_base,
        accords=accords,
        latest_score=latest_score,
        trend_state=trend_state,
        top_opportunity=top_opportunity,
        top_2_differentiators=differentiators[:2],
        top_3_creator_names=top_3_creator_names,
    )


@router.get("/brands/{slug}", response_model=PublicBrandDetail)
def get_public_brand(slug: str, db: Session = Depends(get_db_session)) -> PublicBrandDetail:
    """
    Public brand page data — M0-approved fields only, no auth required.

    Slug: entity_market.entity_id minus 'brand-' prefix.
      e.g. entity_id='brand-creed' → slug='creed'

    Returns 404 if brand not found or has no market data.
    """
    entity_id = f"brand-{slug}"
    em = db.query(EntityMarket).filter(
        EntityMarket.entity_id == entity_id,
        EntityMarket.entity_type == "brand",
    ).first()
    if not em or not _has_data(db, em.id):
        raise HTTPException(status_code=404, detail=f"Brand not found: {slug}")

    latest_score, trend_state = _get_latest_score_and_trend(db, em.id)

    # Total perfumes in KB
    perfume_count_row = _safe(lambda: db.execute(text("""
        SELECT COUNT(*) FROM resolver_perfumes rp
        JOIN resolver_brands rb ON rp.brand_id = rb.id
        WHERE LOWER(rb.canonical_name) = LOWER(:n)
    """), {"n": em.canonical_name}).fetchone(), None, "perfume_count")
    perfume_count = int(perfume_count_row[0]) if perfume_count_row else 0

    # Top 5 tracked perfumes — only entities with data.
    # slug for each = _slugify_canonical(entity_id = canonical_name)
    top_rows = _safe(lambda: db.execute(text("""
        SELECT em2.entity_id, em2.canonical_name,
               etd.composite_market_score, etd.trend_state
        FROM entity_market em2
        LEFT JOIN LATERAL (
            SELECT composite_market_score, trend_state
            FROM entity_timeseries_daily
            WHERE entity_id = em2.id AND mention_count > 0
            ORDER BY date DESC LIMIT 1
        ) etd ON TRUE
        WHERE em2.entity_type = 'perfume'
          AND LOWER(em2.brand_name) = LOWER(:n)
          AND EXISTS (
              SELECT 1 FROM entity_timeseries_daily
              WHERE entity_id = em2.id AND mention_count > 0
          )
        ORDER BY COALESCE(etd.composite_market_score, 0) DESC
        LIMIT 5
    """), {"n": em.canonical_name}).fetchall(), [], "top_perfumes")

    top_5_perfumes = [
        PublicPerfumeRow(
            # slug = URL-safe version of entity_id (which = canonical_name for perfumes)
            slug=_slugify_canonical(r[0]),
            canonical_name=r[1],
            latest_score=float(r[2]) if r[2] is not None else None,
            trend_state=r[3],
        )
        for r in top_rows
    ]

    return PublicBrandDetail(
        slug=slug,
        canonical_name=em.canonical_name,
        latest_score=latest_score,
        trend_state=trend_state,
        perfume_count=perfume_count,
        top_5_perfumes=top_5_perfumes,
    )


@router.get("/sitemap/perfumes", response_model=List[SitemapPerfumeEntry])
def sitemap_perfumes(db: Session = Depends(get_db_session)) -> List[SitemapPerfumeEntry]:
    """
    Slug list for perfume sitemap generation.
    Only entities with market data (anti-thin-content rule) — no dead URLs.
    slug = _slugify_canonical(entity_id = canonical_name)
    """
    rows = _safe(lambda: db.execute(text("""
        SELECT em.entity_id, em.canonical_name, em.brand_name
        FROM entity_market em
        WHERE em.entity_type = 'perfume'
          AND EXISTS (
              SELECT 1 FROM entity_timeseries_daily
              WHERE entity_id = em.id AND mention_count > 0
          )
        ORDER BY em.canonical_name
    """)).fetchall(), [], "sitemap_perfumes")
    return [
        SitemapPerfumeEntry(
            slug=_slugify_canonical(r[0]),  # r[0] = entity_id = canonical_name
            canonical_name=r[1],
            brand_name=r[2],
        )
        for r in rows
    ]


@router.get("/sitemap/brands", response_model=List[SitemapBrandEntry])
def sitemap_brands(db: Session = Depends(get_db_session)) -> List[SitemapBrandEntry]:
    """
    Slug list for brand sitemap generation.
    Only brands with market data.
    slug = entity_id minus 'brand-' prefix (brands ARE pre-slugified in entity_id)
    """
    rows = _safe(lambda: db.execute(text("""
        SELECT em.entity_id, em.canonical_name
        FROM entity_market em
        WHERE em.entity_type = 'brand'
          AND EXISTS (
              SELECT 1 FROM entity_timeseries_daily
              WHERE entity_id = em.id AND mention_count > 0
          )
        ORDER BY em.canonical_name
    """)).fetchall(), [], "sitemap_brands")
    return [
        SitemapBrandEntry(
            slug=_brand_slug_from_entity_id(r[0]),
            canonical_name=r[1],
        )
        for r in rows
    ]
