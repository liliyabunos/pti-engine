#!/usr/bin/env python3
"""
Step 5B — Dev backfill: create pipeline data in market_dev.db so the
aggregation job has content to process.

What this script does:
  1. Creates canonical_content_items and resolved_signals tables in market_dev.db
     (same schema as NormalizedContentStore / SignalStore so the existing
     aggregation job can read them without modification).
  2. Inserts synthetic but realistic mention records for 8 well-known perfumes
     across 3 consecutive dates (BASE_DATE -2, -1, 0) to produce enough
     history to test momentum, acceleration, and breakout signals.
  3. Escalating mention volumes for select perfumes so BreakoutDetector
     fires at least one breakout signal.

This is explicitly a DEV-STAGE backfill. It is not connected to any live
API or real ingestion pipeline. It replaces missing historical data after
the destructive migration 003 cleared the entity_mentions table.

Usage:
    python scripts/dev_backfill_mentions.py
    python scripts/dev_backfill_mentions.py --db outputs/market_dev.db --base-date 2026-04-10
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)

DEFAULT_DB = PROJECT_ROOT / "outputs" / "market_dev.db"

# ---------------------------------------------------------------------------
# Perfume catalog: top tracked entities for dev backfill
# ---------------------------------------------------------------------------
# entity_id      : canonical name (becomes EntityMarket.entity_id)
# brand_name     : for text_content realism
# mentions_by_day: [day-2, day-1, day-0] mention count per day
# engagement_base: base engagement total per mention
# platforms      : platforms to spread mentions across
# ---------------------------------------------------------------------------

DEV_ENTITIES = [
    {
        "entity_id": "Parfums de Marly Delina",
        "brand_name": "Parfums de Marly",
        "mentions_by_day": [3, 5, 12],   # breakout spike on day 0
        "engagement_base": 85_000,
        "platforms": ["youtube", "tiktok", "other"],
    },
    {
        "entity_id": "Maison Francis Kurkdjian Baccarat Rouge 540",
        "brand_name": "Maison Francis Kurkdjian",
        "mentions_by_day": [8, 9, 10],   # steady growth
        "engagement_base": 120_000,
        "platforms": ["youtube", "tiktok"],
    },
    {
        "entity_id": "Byredo Gypsy Water",
        "brand_name": "Byredo",
        "mentions_by_day": [2, 3, 4],
        "engagement_base": 55_000,
        "platforms": ["tiktok", "other"],
    },
    {
        "entity_id": "Xerjoff Erba Pura",
        "brand_name": "Xerjoff",
        "mentions_by_day": [1, 4, 9],    # acceleration spike
        "engagement_base": 70_000,
        "platforms": ["youtube", "tiktok"],
    },
    {
        "entity_id": "Yves Saint Laurent Libre",
        "brand_name": "Yves Saint Laurent",
        "mentions_by_day": [5, 4, 4],    # slight decline
        "engagement_base": 95_000,
        "platforms": ["youtube", "tiktok", "other"],
    },
    {
        "entity_id": "Montale Velvet Fantasy",
        "brand_name": "Montale",
        "mentions_by_day": [1, 1, 2],
        "engagement_base": 30_000,
        "platforms": ["tiktok"],
    },
    {
        "entity_id": "Creed Aventus",
        "brand_name": "Creed",
        "mentions_by_day": [6, 7, 8],
        "engagement_base": 100_000,
        "platforms": ["youtube", "tiktok", "other"],
    },
    {
        "entity_id": "Tom Ford Black Orchid",
        "brand_name": "Tom Ford",
        "mentions_by_day": [2, 2, 3],
        "engagement_base": 65_000,
        "platforms": ["youtube", "tiktok"],
    },
]

# Platform → account handle patterns
_HANDLES = {
    "youtube": ["perfume_guru_{}", "fragrance_lab_{}", "scentstory_{}"],
    "tiktok":  ["scentlover_{}", "perfumepicker_{}", "fragrancetok_{}"],
    "other":   ["fragrance_fan_{}", "reddit_user_{}"],
}

_CONTENT_TEMPLATES = {
    "youtube": "My honest review of {} — is it worth the price? Full breakdown.",
    "tiktok":  "Obsessed with {} right now #perfume #fragrance #fyp",
    "other":   "Is {} really worth the hype? Long-term thoughts after 3 months.",
}

_ENGAGEMENT_BY_PLATFORM = {
    "youtube": {"views_mult": 1.0, "likes_mult": 0.05, "comments_mult": 0.015},
    "tiktok":  {"views_mult": 2.0, "likes_mult": 0.08, "comments_mult": 0.02},
    "other":   {"views_mult": 0.0, "likes_mult": 0.004, "comments_mult": 0.001},
}

_INFLUENCE_BY_PLATFORM = {
    "youtube": 75.0,
    "tiktok": 55.0,
    "other": 30.0,
}


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

CREATE_CANONICAL_CONTENT_ITEMS = """
CREATE TABLE IF NOT EXISTS canonical_content_items (
    id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    source_platform TEXT NOT NULL,
    source_account_id TEXT NULL,
    source_account_handle TEXT NULL,
    source_account_type TEXT NULL,
    source_url TEXT NOT NULL,
    external_content_id TEXT NULL,
    published_at TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    content_type TEXT NOT NULL,
    title TEXT NULL,
    caption TEXT NULL,
    text_content TEXT NULL,
    hashtags_json TEXT NOT NULL DEFAULT '[]',
    mentions_raw_json TEXT NOT NULL DEFAULT '[]',
    media_metadata_json TEXT NOT NULL DEFAULT '{}',
    engagement_json TEXT NOT NULL DEFAULT '{}',
    language TEXT NULL,
    region TEXT NOT NULL DEFAULT 'US',
    raw_payload_ref TEXT NOT NULL DEFAULT '',
    normalizer_version TEXT NOT NULL DEFAULT '1.0',
    query TEXT NULL
)
"""

CREATE_RESOLVED_SIGNALS = """
CREATE TABLE IF NOT EXISTS resolved_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_item_id TEXT NOT NULL,
    resolver_version TEXT NOT NULL DEFAULT '1.0',
    resolved_entities_json TEXT NOT NULL DEFAULT '[]',
    unresolved_mentions_json TEXT NOT NULL DEFAULT '[]',
    alias_candidates_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _init_pipeline_tables(conn: sqlite3.Connection) -> None:
    conn.execute(CREATE_CANONICAL_CONTENT_ITEMS)
    conn.execute(CREATE_RESOLVED_SIGNALS)
    conn.commit()


def _already_seeded(conn: sqlite3.Connection, item_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM canonical_content_items WHERE id = ?", (item_id,)
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------------

def _generate_items_and_signals(base_date_str: str) -> tuple[list, list]:
    """Generate (content_items, resolved_signals) for all entities and 3 days."""
    base = datetime.fromisoformat(base_date_str).replace(tzinfo=timezone.utc)
    days = [base - timedelta(days=2), base - timedelta(days=1), base]

    content_items = []
    resolved_signals = []

    for entity in DEV_ENTITIES:
        eid = entity["entity_id"]
        platforms = entity["platforms"]
        for day_idx, target_day in enumerate(days):
            mention_count = entity["mentions_by_day"][day_idx]
            eng_base = entity["engagement_base"]
            date_str = target_day.strftime("%Y-%m-%d")

            # Distribute mentions across platforms
            platform_cycle = [platforms[i % len(platforms)] for i in range(mention_count)]

            for mention_idx, platform in enumerate(platform_cycle):
                item_id = f"dev_{date_str}_{eid.replace(' ', '_')}_{mention_idx}"

                if item_id in {c["id"] for c in content_items}:
                    continue  # already in this batch

                handle_template = _HANDLES[platform][mention_idx % len(_HANDLES[platform])]
                handle = handle_template.format(mention_idx + 1)

                mult = _ENGAGEMENT_BY_PLATFORM[platform]
                engagement = {
                    "views": int(eng_base * mult["views_mult"]) if mult["views_mult"] else None,
                    "likes": int(eng_base * mult["likes_mult"]),
                    "comments": int(eng_base * mult["comments_mult"]),
                }

                meta = {
                    "source_type": "influencer" if platform == "youtube" else "user",
                    "influence_score": _INFLUENCE_BY_PLATFORM[platform],
                }

                published_at = (
                    target_day.replace(hour=10 + mention_idx, minute=0, second=0)
                    .isoformat()
                    .replace("+00:00", "+00:00")
                )

                content_type = {"youtube": "video", "tiktok": "short", "other": "post"}[platform]

                content_items.append({
                    "id": item_id,
                    "schema_version": "1.0",
                    "source_platform": platform,
                    "source_account_handle": handle,
                    "source_account_type": "creator",
                    "source_url": f"https://{platform}.com/{handle}/{item_id}",
                    "published_at": published_at,
                    "collected_at": published_at,
                    "content_type": content_type,
                    "title": _CONTENT_TEMPLATES[platform].format(eid),
                    "text_content": _CONTENT_TEMPLATES[platform].format(eid),
                    "engagement_json": json.dumps(engagement),
                    "media_metadata_json": json.dumps(meta),
                    "region": "US",
                    "raw_payload_ref": f"data/raw/dev/{item_id}.json",
                    "normalizer_version": "1.0",
                })

                resolved_entities = [
                    {
                        "entity_type": "perfume",
                        "canonical_name": eid,
                        "entity_id": eid,
                        "matched_from": eid.split()[-1].lower(),
                        "confidence": 1.0,
                        "match_type": "exact",
                    }
                ]
                resolved_signals.append({
                    "content_item_id": item_id,
                    "resolver_version": "1.0",
                    "resolved_entities_json": json.dumps(resolved_entities),
                })

    return content_items, resolved_signals


# ---------------------------------------------------------------------------
# Backfill function
# ---------------------------------------------------------------------------

def backfill(db_path: str, base_date: str) -> dict:
    """Create pipeline data in market_dev.db for the given base date and 2 prior days.

    Args:
        db_path:   Path to market_dev.db.
        base_date: ISO date string YYYY-MM-DD (the most recent date).

    Returns:
        Summary dict.
    """
    conn = _connect(db_path)
    _init_pipeline_tables(conn)

    content_items, resolved_signals = _generate_items_and_signals(base_date)

    inserted_items = 0
    skipped_items = 0
    for item in content_items:
        if _already_seeded(conn, item["id"]):
            skipped_items += 1
            continue
        conn.execute(
            """
            INSERT INTO canonical_content_items
                (id, schema_version, source_platform, source_account_handle,
                 source_account_type, source_url, published_at, collected_at,
                 content_type, title, text_content, engagement_json,
                 media_metadata_json, region, raw_payload_ref, normalizer_version,
                 hashtags_json, mentions_raw_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                item["id"], item["schema_version"], item["source_platform"],
                item.get("source_account_handle"), item.get("source_account_type"),
                item["source_url"], item["published_at"], item["collected_at"],
                item["content_type"], item.get("title"), item.get("text_content"),
                item["engagement_json"], item["media_metadata_json"],
                item["region"], item["raw_payload_ref"], item["normalizer_version"],
                "[]", "[]",
            ),
        )
        inserted_items += 1

    inserted_signals = 0
    for sig in resolved_signals:
        # Skip if already seeded (idempotent check on content_item_id)
        exists = conn.execute(
            "SELECT 1 FROM resolved_signals WHERE content_item_id = ?",
            (sig["content_item_id"],),
        ).fetchone()
        if exists:
            continue
        conn.execute(
            """
            INSERT INTO resolved_signals
                (content_item_id, resolver_version, resolved_entities_json)
            VALUES (?, ?, ?)
            """,
            (sig["content_item_id"], sig["resolver_version"], sig["resolved_entities_json"]),
        )
        inserted_signals += 1

    conn.commit()
    conn.close()

    base = datetime.fromisoformat(base_date)
    earliest = (base - timedelta(days=2)).strftime("%Y-%m-%d")

    return {
        "db_path": db_path,
        "base_date": base_date,
        "date_range": f"{earliest} → {base_date}",
        "entities": len(DEV_ENTITIES),
        "content_items_inserted": inserted_items,
        "content_items_skipped": skipped_items,
        "resolved_signals_inserted": inserted_signals,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Dev backfill: seed pipeline tables in market_dev.db."
    )
    p.add_argument("--db", default=str(DEFAULT_DB), help="DB path")
    p.add_argument(
        "--base-date", default="2026-04-10",
        help="Most recent date (YYYY-MM-DD). Two prior days are also seeded.",
    )
    return p


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parser().parse_args()

    result = backfill(args.db, args.base_date)
    print(f"\nDev backfill complete:")
    print(f"  Entities:               {result['entities']}")
    print(f"  Date range:             {result['date_range']}")
    print(f"  content_items inserted: {result['content_items_inserted']}")
    print(f"  content_items skipped:  {result['content_items_skipped']} (already existed)")
    print(f"  resolved_signals inserted: {result['resolved_signals_inserted']}")
    print(f"  DB: {result['db_path']}")
    print(f"\nNext step — run aggregation for each date:")
    base = datetime.fromisoformat(args.base_date)
    for d in [base - timedelta(days=2), base - timedelta(days=1), base]:
        print(f"  PTI_DB_PATH={args.db} python -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics --date {d.strftime('%Y-%m-%d')}")


if __name__ == "__main__":
    main()
