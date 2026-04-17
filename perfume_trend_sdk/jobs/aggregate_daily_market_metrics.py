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
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from perfume_trend_sdk.analysis.market_signals.aggregator import (
    DailyAggregator,
    generate_ticker,
)
from perfume_trend_sdk.bridge.identity_resolver import IdentityResolver
from perfume_trend_sdk.db.market.brand import Brand
from perfume_trend_sdk.db.market.entity_mention import EntityMention
from perfume_trend_sdk.db.market.entity_timeseries_daily import EntityTimeSeriesDaily
from perfume_trend_sdk.db.market.models import Base, EntityMarket
from perfume_trend_sdk.db.market.perfume import Perfume
from perfume_trend_sdk.db.market.session import _make_engine, get_database_url

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
        em = EntityMarket(
            entity_id=canonical_name,
            entity_type="perfume",
            ticker=ticker,
            canonical_name=canonical_name,
            brand_name=brand_name,
            created_at=_now(),
        )
        db.add(em)
        db.flush()
    elif em.brand_name is None:
        # Back-fill brand_name for existing rows that predate this field.
        em.brand_name = _resolve_brand_name(db, _slugify(canonical_name))
    return em


def _upsert_brand(db: Session, canonical_name: str) -> Optional[Brand]:
    slug = _slugify(canonical_name)
    brand = db.query(Brand).filter_by(slug=slug).first()
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
    2. Only if the perfume is genuinely absent from the catalog, fall back to
       splitting the canonical name to derive a brand name. This is the 'new
       entity not yet in seed' path (e.g. a trending niche perfume that hasn't
       been seeded yet).
    """
    slug = _slugify(canonical_name)
    existing = db.query(Perfume).filter_by(slug=slug).first()
    if existing is not None:
        # Perfume is already in catalog with its authoritative brand link.
        return

    # Heuristic: last-word split as last resort for un-seeded entities.
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

            # --- Step 7B / 7.1A: bridge-first UUID resolution ---
            entity_uuid: Optional[uuid.UUID] = None

            # Path 1: integer resolver id → market UUID via bridge
            # Route to perfume or brand lookup based on entity_type.
            is_int_id = raw_eid is not None and (
                isinstance(raw_eid, int)
                or (isinstance(raw_eid, str) and raw_eid.isdigit())
            )
            if is_int_id and identity_resolver is not None:
                if entity_type == "brand":
                    uuid_str = identity_resolver.brand_uuid(int(raw_eid))
                else:
                    uuid_str = identity_resolver.perfume_uuid(int(raw_eid))
                if uuid_str:
                    try:
                        entity_uuid = uuid.UUID(uuid_str)
                    except ValueError:
                        pass

            # Path 2: canonical-name in-process map (dev-backfill / new entities)
            if entity_uuid is None:
                entity_uuid = entity_uuid_map.get(canonical)

            # Path 3: unmapped — log and skip
            if entity_uuid is None:
                _emit_unmapped(
                    resolver_entity_id=raw_eid,
                    entity_type=entity_type,
                    canonical_name=canonical,
                    content_item_id=cid,
                    reason=(
                        "bridge_miss" if is_int_id else "canonical_not_in_entity_market"
                    ),
                )
                continue

            exists = (
                db.query(EntityMention)
                .filter_by(entity_id=entity_uuid, source_url=cid)
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

            db.add(EntityMention(
                entity_id=entity_uuid,
                entity_type=entity_type,
                source_platform=item.get("source_platform"),
                source_url=_resolve_source_url(item, cid),
                author_id=item.get("source_account_handle"),
                mention_count=1.0,
                influence_score=float(meta.get("influence_score") or 0),
                confidence=float(ent.get("confidence") or 1.0),
                engagement=eng_total or None,
                occurred_at=occurred_at,
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

    # Write snapshots using UUID entity_id
    for snap in snapshots:
        canonical = snap["entity_id"]
        entity_uuid = entity_uuid_map.get(canonical)
        if entity_uuid is None:
            continue
        _upsert_snapshot(db, snap, entity_uuid, target_date_obj)

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

    logger.info(
        "aggregate_daily_market_metrics_completed date=%s entities=%d carry_forward=%d mentions=%d",
        target_date, len(snapshots), cf_written, mentions_written,
    )

    return {
        "target_date": target_date,
        "entities_processed": len(snapshots),
        "carry_forward": cf_written,
        "mentions_written": mentions_written,
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
    engine = _make_engine(url)
    Base.metadata.create_all(engine)

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

    from sqlalchemy.orm import sessionmaker
    Session_ = sessionmaker(bind=engine)
    with Session_() as session:
        summary = run(session, target_date=args.date, identity_resolver=identity_resolver)
        session.commit()
    print(summary)


if __name__ == "__main__":
    main()
