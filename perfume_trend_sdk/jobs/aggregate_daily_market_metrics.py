from __future__ import annotations

"""
Job: aggregate_daily_market_metrics

Reads from the existing pipeline tables (canonical_content_items,
resolved_signals) via SQLAlchemy text queries, runs the pure-function
aggregation logic, then writes results to market engine tables via ORM.

Entity UUID flow:
  1. Upsert string canonical name → EntityMarket (gets UUID .id)
  2. Use EntityMarket.id (UUID) when writing to:
       entity_timeseries_daily.entity_id
       entity_mentions.entity_id

Usage (standalone):
    python -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics \
        --date 2026-04-10

Usage (programmatic):
    from perfume_trend_sdk.jobs.aggregate_daily_market_metrics import run
    summary = run(db=session, target_date="2026-04-10")
"""

import argparse
import json
import logging
import math
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from perfume_trend_sdk.analysis.market_signals.aggregator import (
    DailyAggregator,
    generate_ticker,
)
from perfume_trend_sdk.analysis.market_signals.trend_state import compute_trend_state
from perfume_trend_sdk.bridge.identity_resolver import IdentityResolver
from perfume_trend_sdk.db.market.brand import Brand
from perfume_trend_sdk.db.market.entity_mention import EntityMention
from perfume_trend_sdk.db.market.entity_timeseries_daily import EntityTimeSeriesDaily
from perfume_trend_sdk.db.market.models import Base, EntityMarket
from perfume_trend_sdk.db.market.perfume import Perfume
from perfume_trend_sdk.db.market.session import _make_engine, get_database_url, make_session_factory
from perfume_trend_sdk.db.market.source_intelligence import MentionSource, SourceProfile

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Unmapped-entity sink (Step 7C)
# ---------------------------------------------------------------------------
# Writes one JSON line per unmapped entity to outputs/unmapped_entities.jsonl
# so they can be reviewed and mapped/seeded later.

_UNMAPPED_SINK = Path(os.environ.get("PTI_UNMAPPED_LOG", "outputs/unmapped_entities.jsonl"))


def _emit_unmapped(
    *,
    resolver_entity_id: Any,
    entity_type: str,
    canonical_name: str,
    content_item_id: str,
    reason: str,
) -> None:
    """Append one line to the unmapped-entity JSONL review file."""
    _UNMAPPED_SINK.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "resolver_entity_id": resolver_entity_id,
        "entity_type": entity_type,
        "canonical_name": canonical_name,
        "slug": re.sub(r"[\s_]+", "-", re.sub(r"[^\w\s-]", "", canonical_name.lower().strip())).strip("-"),
        "content_item_id": content_item_id,
        "reason": reason,
    }
    logger.warning(
        "unmapped_entity resolver_id=%s type=%s name=%r reason=%s cid=%s",
        resolver_entity_id, entity_type, canonical_name, reason, content_item_id,
    )
    with _UNMAPPED_SINK.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(value: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", value.lower().strip())
    return re.sub(r"[\s_]+", "-", slug).strip("-")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Load pipeline data via text() — pipeline tables have no ORM model
# ---------------------------------------------------------------------------

def _load_content_items(db: Session) -> List[Dict[str, Any]]:
    rows = db.execute(text("""
        SELECT
            id, source_platform, source_account_handle,
            source_url, external_content_id,
            published_at, engagement_json, media_metadata_json,
            text_content, title, content_type
        FROM canonical_content_items
    """)).fetchall()
    return [dict(r._mapping) for r in rows]


def _load_resolved_signals(db: Session) -> List[Dict[str, Any]]:
    rows = db.execute(text("""
        SELECT content_item_id, resolver_version, resolved_entities_json
        FROM resolved_signals
    """)).fetchall()
    return [dict(r._mapping) for r in rows]


def _load_prev_snapshots(
    db: Session, entity_uuids: List[uuid.UUID], before_date: str
) -> Dict[uuid.UUID, Dict[str, Any]]:
    """Return most-recent snapshot strictly before before_date per entity UUID."""
    if not entity_uuids:
        return {}
    prev: Dict[uuid.UUID, Dict[str, Any]] = {}
    for uid in entity_uuids:
        row = (
            db.query(EntityTimeSeriesDaily)
            .filter(
                EntityTimeSeriesDaily.entity_id == uid,
                EntityTimeSeriesDaily.date < before_date,
            )
            .order_by(EntityTimeSeriesDaily.date.desc())
            .first()
        )
        if row:
            prev[uid] = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    return prev


# ---------------------------------------------------------------------------
# Upsert helpers — all return ORM objects so callers can access .id
# ---------------------------------------------------------------------------

def _resolve_brand_name(db: Session, perfume_slug: str) -> Optional[str]:
    """Look up brand name via the perfumes→brands catalog JOIN.

    Uses a raw SQL query so it stays compatible with both SQLite (dev) and
    PostgreSQL (prod) without relying on SQLAlchemy relationship loading order.
    """
    try:
        row = db.execute(
            text(
                "SELECT b.name FROM perfumes p "
                "JOIN brands b ON p.brand_id = b.id "
                "WHERE p.slug = :slug LIMIT 1"
            ),
            {"slug": perfume_slug},
        ).fetchone()
        return row[0] if row else None
    except Exception:
        return None


def _upsert_entity_market(db: Session, canonical_name: str, ticker: str) -> EntityMarket:
    em = db.query(EntityMarket).filter_by(entity_id=canonical_name).first()
    if em is None:
        brand_name = _resolve_brand_name(db, _slugify(canonical_name))
        try:
            sp = db.begin_nested()  # savepoint — allows rollback without losing session state
            em = EntityMarket(
                entity_id=canonical_name,
                entity_type="perfume",
                ticker=ticker,
                canonical_name=canonical_name,
                brand_name=brand_name,
                created_at=_now(),
            )
            db.add(em)
            sp.commit()
        except IntegrityError:
            # Row was inserted by a concurrent run or a prior aggregation pass for this date.
            sp.rollback()
            em = db.query(EntityMarket).filter_by(entity_id=canonical_name).first()
    if em is not None and em.brand_name is None:
        # Back-fill brand_name for existing rows that predate this field.
        em.brand_name = _resolve_brand_name(db, _slugify(canonical_name))
    return em


def _upsert_brand(db: Session, canonical_name: str) -> Optional[Brand]:
    slug = _slugify(canonical_name)
    brand = db.query(Brand).filter_by(slug=slug).first()
    if brand is None:
        # Also check by name — the unique constraint is on name, not slug
        brand = db.query(Brand).filter(Brand.name == canonical_name).first()
    if brand is None:
        ticker = generate_ticker(canonical_name)[:5]
        if db.query(Brand).filter_by(ticker=ticker).first() is not None:
            ticker = ticker[:4] + "X"
        brand = Brand(
            name=canonical_name,
            slug=slug,
            ticker=ticker,
            created_at=_now(),
        )
        db.add(brand)
        db.flush()
    return brand


def _upsert_perfume(
    db: Session,
    canonical_name: str,
    brand: Optional[Brand],
    ticker: str,
) -> None:
    slug = _slugify(canonical_name)
    existing = db.query(Perfume).filter_by(slug=slug).first()
    if existing is None:
        # Resolve ticker collisions with an incrementing numeric suffix so that
        # two canonically distinct perfumes with identical tickers (e.g. different
        # brand spellings of the same fragrance) don't crash the aggregation job.
        if db.query(Perfume).filter_by(ticker=ticker).first() is not None:
            base = ticker[:4]
            for i in range(1, 100):
                candidate = f"{base}{i:02d}"
                if db.query(Perfume).filter_by(ticker=candidate).first() is None:
                    ticker = candidate
                    break
        db.add(Perfume(
            brand_id=brand.id if brand else None,
            name=canonical_name,
            slug=slug,
            ticker=ticker,
            created_at=_now(),
        ))


def _upsert_brand_and_perfume_catalog_first(
    db: Session,
    canonical_name: str,
    ticker: str,
) -> None:
    """Catalog-first brand/perfume upsert (Step 9B).

    1. If the perfume slug already exists in the catalog, trust its existing
       brand link and return — no heuristic derivation attempted.
    2. If the perfume exists in resolver_fragrance_master (e.g. g2_entity_seed
       entities seeded via scripts/seed_g2_missing_perfumes.py), use the
       resolver's brand_name — authoritative, no heuristic needed.
    3. Only if both lookups fail, fall back to splitting the canonical name to
       derive a brand name. This is the 'new entity not yet in any seed' path.
    """
    slug = _slugify(canonical_name)
    existing = db.query(Perfume).filter_by(slug=slug).first()
    if existing is not None:
        # Perfume is already in catalog with its authoritative brand link.
        return

    # Step 2: Try resolver_fragrance_master for the correct brand name.
    # Handles entities seeded into resolver_perfumes (e.g. via g2_entity_seed)
    # that have not yet appeared in the market perfumes table.
    # Wrapped in try/except — resolver_* tables are Postgres-only; SQLite dev
    # environments will fall through to the heuristic below.
    brand_name: Optional[str] = None
    norm = slug.replace("-", " ")  # "al-haramain-amber-oud" → "al haramain amber oud"
    try:
        rfm_row = db.execute(
            text(
                "SELECT rfm.brand_name "
                "FROM resolver_fragrance_master rfm "
                "JOIN resolver_perfumes rp ON rp.id = rfm.perfume_id "
                "WHERE rp.normalized_name = :norm "
                "LIMIT 1"
            ),
            {"norm": norm},
        ).fetchone()
        if rfm_row:
            brand_name = rfm_row[0]
    except Exception:
        pass  # resolver tables unavailable in SQLite dev — fall through

    # Step 3: Last-word-split heuristic as final fallback for truly unknown entities.
    if not brand_name:
        parts = canonical_name.rsplit(" ", 1)
        brand_name = parts[0] if len(parts) > 1 else canonical_name

    brand = _upsert_brand(db, brand_name)
    _upsert_perfume(db, canonical_name, brand, ticker)


def _upsert_snapshot(
    db: Session,
    snap: Dict[str, Any],
    entity_uuid: uuid.UUID,
    target_date: date,
) -> None:
    existing = (
        db.query(EntityTimeSeriesDaily)
        .filter_by(entity_id=entity_uuid, entity_type=snap["entity_type"], date=target_date)
        .first()
    )
    now = _now()
    cols = {c.name for c in EntityTimeSeriesDaily.__table__.columns}
    data = {k: v for k, v in snap.items() if k in cols and k not in ("id", "entity_id", "date", "entity_type")}

    if existing:
        for k, v in data.items():
            setattr(existing, k, v)
        existing.updated_at = now
    else:
        db.add(EntityTimeSeriesDaily(
            entity_id=entity_uuid,
            entity_type=snap["entity_type"],
            date=target_date,
            created_at=now,
            updated_at=now,
            **data,
        ))


# ---------------------------------------------------------------------------
# Brand roll-up — aggregate perfume timeseries → brand market rows
# ---------------------------------------------------------------------------

def _rollup_brand_market_data(db: Session, target_date: date) -> int:
    """Create/update brand entity_market and entity_timeseries_daily rows.

    For every brand that has at least one perfume in entity_market with a
    timeseries row for target_date, sum/average the perfume metrics to produce
    a brand-level market snapshot.

    Brand metrics (per date):
      mention_count       = SUM(perfume mention_count)
      engagement_sum      = SUM(perfume engagement_sum)
      unique_authors      = SUM(perfume unique_authors)  [upper bound — may double-count]
      composite_market_score = AVG(perfume composite_market_score) weighted by mention_count
      growth_rate         = weighted avg of growth_rate (weight = mention_count)
      momentum            = AVG(perfume momentum)
      acceleration        = AVG(perfume acceleration)
      volatility          = AVG(perfume volatility)
      confidence_avg      = AVG(perfume confidence_avg)

    Returns the number of brand rows upserted.
    """
    target_str = target_date.isoformat()

    # Fetch per-brand aggregated perfume metrics for target_date.
    # Only include perfumes that have real timeseries data (mention_count > 0)
    # OR carry-forward rows (mention_count = 0) — all rows are included so that
    # brands get a zero-score row even on quiet days, matching carry-forward behavior.
    brand_rows = db.execute(
        text("""
        SELECT
            em.brand_name,
            SUM(etd.mention_count)                             AS total_mentions,
            SUM(etd.engagement_sum)                            AS total_engagement,
            SUM(etd.unique_authors)                            AS total_authors,
            CASE WHEN SUM(etd.mention_count) > 0
                 THEN SUM(etd.composite_market_score * etd.mention_count)
                      / SUM(etd.mention_count)
                 ELSE AVG(etd.composite_market_score)
            END                                                AS wgt_score,
            CASE WHEN SUM(etd.mention_count) > 0
                 THEN SUM(COALESCE(etd.growth_rate, 0) * etd.mention_count)
                      / SUM(etd.mention_count)
                 ELSE AVG(etd.growth_rate)
            END                                                AS wgt_growth,
            AVG(etd.momentum)                                  AS avg_momentum,
            AVG(etd.acceleration)                              AS avg_acceleration,
            AVG(etd.volatility)                                AS avg_volatility,
            AVG(etd.confidence_avg)                            AS avg_confidence
        FROM entity_market em
        JOIN entity_timeseries_daily etd ON etd.entity_id = em.id
        WHERE em.entity_type = 'perfume'
          AND em.brand_name IS NOT NULL
          AND etd.date = :dt
        GROUP BY em.brand_name
        HAVING SUM(etd.mention_count) > 0
        """),
        {"dt": target_str},
    ).fetchall()

    if not brand_rows:
        return 0

    now = _now()
    upserted = 0

    for row in brand_rows:
        brand_name = row[0]
        if not brand_name:
            continue

        total_mentions  = float(row[1] or 0)
        total_engagement = float(row[2] or 0)
        total_authors   = int(row[3] or 0)
        wgt_score       = float(row[4] or 0)
        wgt_growth      = row[5]
        avg_momentum    = row[6]
        avg_acceleration = row[7]
        avg_volatility  = row[8]
        avg_confidence  = row[9]

        # Upsert brand entity_market row
        em = db.query(EntityMarket).filter(
            EntityMarket.entity_type == "brand",
            EntityMarket.canonical_name == brand_name,
        ).first()
        if em is None:
            ticker = generate_ticker(brand_name)
            entity_slug = f"brand-{_slugify(brand_name)}"
            em = EntityMarket(
                entity_id=entity_slug,
                entity_type="brand",
                ticker=ticker,
                canonical_name=brand_name,
                brand_name=brand_name,
                created_at=now,
            )
            db.add(em)
            db.flush()

        # Upsert brand timeseries row for target_date
        existing = db.query(EntityTimeSeriesDaily).filter_by(
            entity_id=em.id,
            entity_type="brand",
            date=target_date,
        ).first()

        gr_val = float(wgt_growth) if wgt_growth is not None else None
        mom_val = float(avg_momentum) if avg_momentum is not None else None
        acc_val = float(avg_acceleration) if avg_acceleration is not None else None

        # Phase I3 — brand trend state derived from aggregated perfume metrics.
        # Prev brand score lookup: use the existing timeseries row for the brand entity
        # if available (set before this block via a prior aggregation date).
        prev_brand_score: Optional[float] = None
        if em is not None:  # em was set earlier in the loop
            prev_row = (
                db.query(EntityTimeSeriesDaily)
                .filter(
                    EntityTimeSeriesDaily.entity_id == em.id,
                    EntityTimeSeriesDaily.date < target_date,
                    EntityTimeSeriesDaily.mention_count > 0,
                )
                .order_by(EntityTimeSeriesDaily.date.desc())
                .first()
            )
            if prev_row:
                prev_brand_score = prev_row.composite_market_score

        brand_trend_state = compute_trend_state(
            score=wgt_score,
            prev_score=prev_brand_score,
            growth_rate=gr_val,
            momentum=mom_val,
            acceleration=acc_val,
            mention_count=total_mentions,
        )

        snap_data = {
            "mention_count":          total_mentions,
            "unique_authors":         total_authors,
            "engagement_sum":         total_engagement,
            "composite_market_score": wgt_score,
            "growth_rate":            gr_val,
            "momentum":               mom_val,
            "acceleration":           acc_val,
            "volatility":             float(avg_volatility) if avg_volatility is not None else None,
            "confidence_avg":         float(avg_confidence) if avg_confidence is not None else None,
            "trend_state":            brand_trend_state,
        }

        if existing:
            for k, v in snap_data.items():
                setattr(existing, k, v)
            existing.updated_at = now
        else:
            db.add(EntityTimeSeriesDaily(
                entity_id=em.id,
                entity_type="brand",
                date=target_date,
                created_at=now,
                updated_at=now,
                **snap_data,
            ))

        upserted += 1

    return upserted


# ---------------------------------------------------------------------------
# Carry-forward — chart continuity on quiet days
# ---------------------------------------------------------------------------

# How many days back to look for active entities.  An entity that had at least
# one real row in the past CARRY_FORWARD_DAYS days gets a zero-mention row for
# target_date if it has no real row yet.  Once an entity goes CARRY_FORWARD_DAYS
# consecutive days with no content, carry-forward stops automatically — this
# bounds row growth to O(active_entities × CARRY_FORWARD_DAYS).
CARRY_FORWARD_DAYS = 7


def _carry_forward_quiet_entities(db: Session, target_date: date) -> int:
    """Insert zero-mention rows for entities active in the last CARRY_FORWARD_DAYS
    days that have no row for target_date.

    Selection logic:
      1. Find every entity_id that has at least one entity_timeseries_daily row
         in the half-open window [target_date - 7d, target_date).
      2. Exclude entity_ids that already have a row for target_date
         (real rows written by the main snapshot pass must not be touched).
      3. For each remaining entity_id, insert a zero-activity row.

    The inserted row carries:
      mention_count = 0, engagement_sum = 0, unique_authors = 0
      growth_rate   = -1.0  (100% decline — honest, not estimated)
      composite_market_score = 0.0
      momentum = acceleration = volatility = 0.0

    This gives Recharts a data point at every date so it can draw a
    continuous line rather than isolated dots.  The score of 0 is correct:
    no content appeared for this entity today.

    Returns the number of rows inserted.
    """
    cutoff = (target_date - timedelta(days=CARRY_FORWARD_DAYS)).isoformat()
    target_str = target_date.isoformat()

    rows = db.execute(
        text("""
            SELECT DISTINCT entity_id
            FROM entity_timeseries_daily
            WHERE date >= :cutoff
              AND date <  :target
              AND mention_count > 0
              AND entity_id NOT IN (
                  SELECT entity_id
                  FROM   entity_timeseries_daily
                  WHERE  date = :target
              )
        """),
        {"cutoff": cutoff, "target": target_str},
    ).fetchall()

    if not rows:
        return 0

    now = _now()
    for (entity_uuid,) in rows:
        db.add(EntityTimeSeriesDaily(
            entity_id=entity_uuid,
            entity_type="perfume",
            date=target_date,
            mention_count=0.0,
            unique_authors=0,
            engagement_sum=0.0,
            sentiment_avg=None,
            confidence_avg=None,
            search_index=None,
            retailer_score=None,
            growth_rate=-1.0,
            composite_market_score=0.0,
            momentum=0.0,
            acceleration=0.0,
            volatility=0.0,
            trend_state=None,  # Phase I3 — no activity, no trend state
            created_at=now,
            updated_at=now,
        ))

    return len(rows)


_YT_URL_PREFIX = "https://www.youtube.com/watch?v="
_TT_URL_PREFIX = "https://www.tiktok.com/@{handle}/video/"


def _resolve_source_url(item: dict, fallback_cid: str) -> str:
    """Return the best available URL for an entity_mentions row.

    Priority:
      1. source_url from the content item if it looks like a real URL
      2. Reconstruct from platform + external_content_id for known platforms
      3. Fall back to content_item_id
    """
    raw_url = item.get("source_url") or ""
    if raw_url.startswith("http"):
        return raw_url

    platform = item.get("source_platform") or ""
    ext_id = item.get("external_content_id") or ""

    if platform == "youtube" and ext_id:
        return f"{_YT_URL_PREFIX}{ext_id}"
    if platform == "tiktok" and ext_id:
        handle = (item.get("source_account_handle") or "").lstrip("@")
        if handle:
            return f"https://www.tiktok.com/@{handle}/video/{ext_id}"
        return f"https://www.tiktok.com/video/{ext_id}"

    return fallback_cid


# ---------------------------------------------------------------------------
# Phase I2 — Source-score computation helpers
# ---------------------------------------------------------------------------

def _compute_source_score(
    platform: str,
    views: Optional[int],
    likes: Optional[int],
    comments_count: Optional[int],
    engagement_rate: Optional[float],
) -> Optional[float]:
    """Compute a [0, 1] quality score for a single mention's source signal.

    YouTube:
        score = 0.70 × view_quality + 0.30 × engagement_bonus
        view_quality   = min(log10(views+1) / log10(100_000), 1.0)
        engagement_bonus = min(engagement_rate × 10, 1.0) if engagement_rate else 0

    Reddit:
        score = 0.60 × upvote_quality + 0.40 × comment_quality
        upvote_quality  = min(log10(upvotes+1) / log10(1_000), 1.0)
        comment_quality = min(log10(comments+1) / log10(100), 1.0)
        Returns None when both upvotes and comments are zero.

    Other platforms: None (no score — no boost, no penalty).
    """
    if platform == "youtube":
        v = max(int(views or 0), 0)
        view_quality = min(math.log10(v + 1) / math.log10(100_000), 1.0)
        eng_bonus = min(float(engagement_rate) * 10.0, 1.0) if engagement_rate else 0.0
        return round(0.70 * view_quality + 0.30 * eng_bonus, 4)

    if platform == "reddit":
        upvotes = max(int(likes or 0), 0)
        comments = max(int(comments_count or 0), 0)
        if upvotes == 0 and comments == 0:
            return None
        upvote_q = min(math.log10(upvotes + 1) / math.log10(1_000), 1.0)
        comment_q = min(math.log10(comments + 1) / math.log10(100), 1.0)
        return round(0.60 * upvote_q + 0.40 * comment_q, 4)

    return None


def _compute_weighted_signal_scores(db: Session, target_date: str) -> int:
    """Compute and store weighted_signal_score for all timeseries rows on target_date.

    Formula (Phase I2):
        weighted_signal_score = MIN(100, composite_market_score × (1.0 + avg_source_quality))

    where:
        avg_source_quality = AVG(mention_sources.source_score) for entity's mentions on date
                           = 0.0 when no source_score data is available (no boost, no penalty)

    This is non-destructive: composite_market_score is unchanged.
    High-quality source evidence (high views, high engagement) boosts the weighted score.
    Entities with no source data maintain their raw composite score (quality=0 → ×1.0).

    Returns the number of timeseries rows updated.
    """
    result = db.execute(text("""
        UPDATE entity_timeseries_daily etd
        SET weighted_signal_score = LEAST(100.0,
            etd.composite_market_score * (
                1.0 + COALESCE((
                    SELECT AVG(ms.source_score)
                    FROM entity_mentions em
                    JOIN mention_sources ms ON ms.mention_id = em.id
                    WHERE em.entity_id = etd.entity_id
                      AND em.occurred_at::date = etd.date
                      AND ms.source_score IS NOT NULL
                ), 0.0)
            )
        )
        WHERE etd.date = :dt
          AND etd.mention_count > 0
    """), {"dt": target_date})
    return result.rowcount


def _write_mentions(
    db: Session,
    content_items: List[Dict[str, Any]],
    resolved_signals: List[Dict[str, Any]],
    target_date: str,
    entity_uuid_map: Dict[str, uuid.UUID],
    identity_resolver: Optional[IdentityResolver] = None,
) -> int:
    """Write EntityMention rows for this date. Skip already-written ones.

    UUID resolution priority (Step 7B):
      1. Bridge lookup via IdentityResolver (resolver integer id → market UUID)
         — used when the resolved entity carries an integer entity_id and the
         mapping table has been populated by sync_identity_map.py.
      2. Canonical-name lookup in entity_uuid_map
         — used when integer id is absent or unmapped (e.g. dev-backfill rows).
      3. Unmapped — entity is logged to outputs/unmapped_entities.jsonl and
         skipped. No invalid rows are written to the market engine.
    """
    items_by_id = {
        item["id"]: item
        for item in content_items
        if (item.get("published_at") or "")[:10] == target_date
    }
    written = 0
    for sig in resolved_signals:
        cid = sig["content_item_id"]
        item = items_by_id.get(cid)
        if item is None:
            continue
        entities = json.loads(sig.get("resolved_entities_json") or "[]")
        meta = json.loads(item.get("media_metadata_json") or "{}")
        engagement = json.loads(item.get("engagement_json") or "{}")
        eng_total = (
            float(engagement.get("views") or 0)
            + float(engagement.get("likes") or 0) * 3
            + float(engagement.get("comments") or 0) * 5
        )
        for ent in entities:
            entity_type = ent.get("entity_type", "perfume")
            if entity_type not in ("perfume", "brand"):
                continue
            canonical = ent.get("canonical_name", "")
            raw_eid = ent.get("entity_id")

            # --- UUID resolution for entity_mentions ---
            # ALWAYS use entity_uuid_map (canonical_name → entity_market.id).
            # entity_mentions.entity_id MUST reference entity_market.id.
            #
            # DO NOT use identity_resolver.perfume_uuid() here — it returns
            # perfume_identity_map.market_perfume_uuid which is a different UUID
            # than entity_market.id. Mixing them breaks Recent Mentions, source
            # intelligence, and driver analysis. (Fixed: 2026-04-24)
            entity_uuid: Optional[uuid.UUID] = entity_uuid_map.get(canonical)

            if entity_uuid is None:
                _emit_unmapped(
                    resolver_entity_id=raw_eid,
                    entity_type=entity_type,
                    canonical_name=canonical,
                    content_item_id=cid,
                    reason="canonical_not_in_entity_market",
                )
                continue

            # Resolve the full source URL once — used consistently for both
            # the dedup check and the INSERT. Previously the check used the
            # bare content_item_id (cid) while the INSERT used the full URL,
            # so the check never matched and every re-run inserted duplicates.
            source_url_resolved = _resolve_source_url(item, cid)

            exists = (
                db.query(EntityMention)
                .filter_by(entity_id=entity_uuid, source_url=source_url_resolved)
                .first()
            )
            if exists:
                continue

            # Parse occurred_at from published_at
            raw_date = (item.get("published_at") or "")[:10]
            try:
                occurred_at = datetime.fromisoformat(raw_date).replace(tzinfo=timezone.utc)
            except ValueError:
                occurred_at = _now()

            mention = EntityMention(
                entity_id=entity_uuid,
                entity_type=entity_type,
                source_platform=item.get("source_platform"),
                source_url=source_url_resolved,
                author_id=item.get("source_account_handle"),
                author_name=meta.get("channel_title") or item.get("source_account_handle"),
                mention_count=1.0,
                influence_score=float(meta.get("influence_score") or 0),
                confidence=float(ent.get("confidence") or 1.0),
                engagement=eng_total or None,
                occurred_at=occurred_at,
                created_at=_now(),
            )
            db.add(mention)
            db.flush()  # get mention.id for MentionSource FK

            # --- Phase I1: source intelligence rows ---
            platform = item.get("source_platform") or "unknown"
            source_id = meta.get("channel_id") or item.get("source_account_handle") or ""
            source_name = meta.get("channel_title") or item.get("source_account_handle")
            views_raw = int(engagement.get("views") or 0)
            likes_raw = int(engagement.get("likes") or 0)
            comments_raw = int(engagement.get("comments") or 0)
            eng_rate: Optional[float] = (
                (likes_raw + comments_raw) / views_raw if views_raw > 0 else None
            )

            if source_id:
                # Upsert source_profiles — ON CONFLICT UPDATE name only
                db.execute(text("""
                    INSERT INTO source_profiles
                        (id, platform, source_id, source_name, created_at, updated_at)
                    VALUES
                        (gen_random_uuid(), :platform, :source_id, :source_name, NOW(), NOW())
                    ON CONFLICT (platform, source_id)
                    DO UPDATE SET
                        source_name = EXCLUDED.source_name,
                        updated_at  = NOW()
                """), {
                    "platform": platform,
                    "source_id": source_id,
                    "source_name": source_name,
                })

            # Phase I2: compute source_score for weighted signal scoring
            src_score = _compute_source_score(
                platform=platform,
                views=views_raw or None,
                likes=likes_raw or None,
                comments_count=comments_raw or None,
                engagement_rate=eng_rate,
            )

            db.add(MentionSource(
                mention_id=mention.id,
                platform=platform,
                source_id=source_id or "",
                source_name=source_name,
                views=views_raw or None,
                likes=likes_raw or None,
                comments_count=comments_raw or None,
                engagement_rate=eng_rate,
                source_score=src_score,
                created_at=_now(),
            ))
            written += 1
    return written


# ---------------------------------------------------------------------------
# Main job function
# ---------------------------------------------------------------------------

def run(
    db: Session,
    target_date: Optional[str] = None,
    identity_resolver: Optional[IdentityResolver] = None,
) -> Dict[str, Any]:
    """Aggregate pipeline data into market engine tables.

    Args:
        db:                Active SQLAlchemy session (caller is responsible for commit).
        target_date:       ISO date (YYYY-MM-DD). Defaults to today.
        identity_resolver: Optional bridge resolver (Step 7B). When provided,
                           resolved integer entity_ids are translated to market
                           UUIDs before falling back to canonical-name lookup.
                           Pass an IdentityResolver instance pointing at the
                           market engine DB that has the mapping tables populated.

    Returns:
        Summary dict: {target_date, entities_processed, mentions_written}.
    """
    if target_date is None:
        target_date = date.today().isoformat()
    target_date_obj = date.fromisoformat(target_date)

    logger.info("aggregate_daily_market_metrics_started date=%s", target_date)

    content_items = _load_content_items(db)
    resolved_signals = _load_resolved_signals(db)

    logger.info(
        "aggregate_data_loaded content_items=%d resolved_signals=%d",
        len(content_items), len(resolved_signals),
    )

    aggregator = DailyAggregator()

    # First pass — discover entity IDs, upsert EntityMarket rows
    tmp_snaps = aggregator.aggregate_from_data(
        content_items=content_items,
        resolved_signals=resolved_signals,
        target_date=target_date,
        prev_snapshots={},
    )

    # Upsert all entity records and build canonical_name → UUID map
    entity_uuid_map: Dict[str, uuid.UUID] = {}
    for snap in tmp_snaps:
        canonical = snap["entity_id"]
        ticker = generate_ticker(canonical)
        em = _upsert_entity_market(db, canonical, ticker)
        entity_uuid_map[canonical] = em.id

        _upsert_brand_and_perfume_catalog_first(db, canonical, ticker)

    db.flush()

    # Load prev snapshots keyed by UUID
    entity_uuids = list(entity_uuid_map.values())
    prev_snapshots_by_uuid = _load_prev_snapshots(db, entity_uuids, before_date=target_date)

    # Remap prev_snapshots to use canonical name as key for aggregator
    uuid_to_canonical = {v: k for k, v in entity_uuid_map.items()}
    prev_snapshots_by_name: Dict[str, Dict[str, Any]] = {
        uuid_to_canonical[uid]: snap
        for uid, snap in prev_snapshots_by_uuid.items()
        if uid in uuid_to_canonical
    }

    # Second pass with real prev data
    snapshots = aggregator.aggregate_from_data(
        content_items=content_items,
        resolved_signals=resolved_signals,
        target_date=target_date,
        prev_snapshots=prev_snapshots_by_name,
    )

    # Write snapshots using UUID entity_id, including trend_state classification
    for snap in snapshots:
        canonical = snap["entity_id"]
        entity_uuid = entity_uuid_map.get(canonical)
        if entity_uuid is None:
            continue
        # Phase I3 — compute trend state from current snapshot + previous day context
        prev = prev_snapshots_by_uuid.get(entity_uuid, {})
        snap["trend_state"] = compute_trend_state(
            score=float(snap.get("composite_market_score") or 0.0),
            prev_score=prev.get("composite_market_score"),
            growth_rate=snap.get("growth_rate"),
            momentum=snap.get("momentum"),
            acceleration=snap.get("acceleration"),
            mention_count=float(snap.get("mention_count") or 0.0),
        )
        _upsert_snapshot(db, snap, entity_uuid, target_date_obj)

    db.flush()

    # Brand roll-up: aggregate perfume timeseries → brand entity_market rows.
    # Runs after perfume snapshots are committed so the JOIN has data to aggregate.
    brand_rows_written = _rollup_brand_market_data(db, target_date_obj)
    if brand_rows_written:
        logger.info(
            "brand_rollup_written date=%s count=%d",
            target_date, brand_rows_written,
        )
        db.flush()

    # Carry-forward: entities active in the past 7 days but silent today
    # get a zero-mention row so chart lines remain continuous.
    cf_written = _carry_forward_quiet_entities(db, target_date_obj)
    if cf_written:
        logger.info(
            "carry_forward_written date=%s count=%d",
            target_date, cf_written,
        )
        db.flush()

    mentions_written = _write_mentions(
        db, content_items, resolved_signals, target_date, entity_uuid_map,
        identity_resolver=identity_resolver,
    )

    # Phase I2: compute weighted_signal_score after mentions (and their source_scores) are written
    db.flush()
    weighted_updated = _compute_weighted_signal_scores(db, target_date)
    if weighted_updated:
        logger.info(
            "weighted_signal_scores_computed date=%s rows=%d",
            target_date, weighted_updated,
        )

    # Phase I3 — count trend states written
    trend_state_counts: dict = {}
    for snap in snapshots:
        ts = snap.get("trend_state")
        if ts:
            trend_state_counts[ts] = trend_state_counts.get(ts, 0) + 1

    logger.info(
        "aggregate_daily_market_metrics_completed date=%s entities=%d brands=%d carry_forward=%d mentions=%d weighted=%d trend_states=%s",
        target_date, len(snapshots), brand_rows_written, cf_written, mentions_written, weighted_updated,
        trend_state_counts,
    )

    return {
        "target_date": target_date,
        "entities_processed": len(snapshots),
        "brand_rows_written": brand_rows_written,
        "carry_forward": cf_written,
        "mentions_written": mentions_written,
        "weighted_updated": weighted_updated,
        "trend_states": trend_state_counts,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Aggregate daily market metrics.")
    p.add_argument("--date", default=None, help="ISO date YYYY-MM-DD (default: today)")
    p.add_argument(
        "--resolver-db", default=None,
        help=(
            "Path to market engine DB that has the identity mapping tables "
            "(brand_identity_map, perfume_identity_map). When provided, resolved "
            "integer entity_ids are translated to market UUIDs via the bridge. "
            "Defaults to PTI_DB_PATH env var value (same DB as the market engine)."
        ),
    )
    return p


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args()

    # Load .env so PTI_DB_PATH / DATABASE_URL are available when running as CLI.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    url = get_database_url()

    # Build IdentityResolver if mapping tables are available.
    # Identity maps (brand_identity_map, perfume_identity_map) live in the
    # market engine DB. In production DATABASE_URL is the market DB, so the
    # resolver must point there — not at the resolver catalog SQLite (pti.db).
    resolver_db_path = (
        args.resolver_db                       # explicit CLI override always wins
        or os.environ.get("DATABASE_URL")      # production Postgres — identity maps are here
        or os.environ.get("PTI_DB_PATH")       # local SQLite market dev DB
        or "outputs/pti.db"                    # last-resort fallback
    )
    identity_resolver: Optional[IdentityResolver] = None
    try:
        ir = IdentityResolver(resolver_db_path)
        stats = ir.stats()
        if stats["brand_mappings"] > 0 or stats["perfume_mappings"] > 0:
            identity_resolver = ir
            logger.info(
                "bridge_loaded brands=%d perfumes=%d",
                stats["brand_mappings"], stats["perfume_mappings"],
            )
        else:
            logger.info("bridge_empty db=%s — skipping bridge resolution", resolver_db_path)
    except Exception as exc:
        logger.warning("bridge_unavailable reason=%s", exc)

    Session_ = make_session_factory(url)
    with Session_() as session:
        summary = run(session, target_date=args.date, identity_resolver=identity_resolver)
        session.commit()
    print(summary)


if __name__ == "__main__":
    main()
