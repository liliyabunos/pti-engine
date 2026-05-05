#!/usr/bin/env python3
"""
C1.3 — Compute creator_entity_relationships from existing ingestion data.

Aggregates per (platform, creator_id, entity_id):
  - mention count and unique content count
  - first/last mention dates
  - total/avg views, likes, comments
  - avg engagement rate (from mention_sources if available, else derived)
  - mentions_before_first_breakout / days_before_first_breakout

Usage:
    python3 scripts/compute_creator_entity_relationships.py --dry-run
    python3 scripts/compute_creator_entity_relationships.py --apply
    python3 scripts/compute_creator_entity_relationships.py --apply --limit 500
    python3 scripts/compute_creator_entity_relationships.py --verify

Notes:
  - engagement_json is stored as TEXT in canonical_content_items — always cast ::jsonb
  - The join handles both old (bare video ID) and new (full URL) source_url patterns
  - entity_id in entity_mentions is varchar UUID — cast to ::uuid for UUID comparisons
  - Only YouTube source_platform currently (Reddit has no channel_id equivalent)
  - Idempotent: UPSERT ON CONFLICT updates all fields
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2
import psycopg2.extras

logging.basicConfig(
    format="%(asctime)s %(levelname)-7s %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

_UPSERT_BATCH = 200
_PLATFORM = "youtube"


def _get_conn():
    url = os.environ.get("DATABASE_URL", "")
    if not url or url.startswith("sqlite"):
        log.error("DATABASE_URL not set or points to SQLite — PostgreSQL required.")
        sys.exit(1)
    return psycopg2.connect(url)


# ---------------------------------------------------------------------------
# Step 1 — Load first breakout/acceleration_spike signal date per entity
# ---------------------------------------------------------------------------

def _load_first_signals(cur) -> dict[str, datetime]:
    """Return {entity_id_str: first_breakout_date} for breakout/acceleration_spike."""
    cur.execute("""
        SELECT
            entity_id::text,
            MIN(detected_at) AS first_signal_date
        FROM signals
        WHERE signal_type IN ('breakout', 'acceleration_spike')
        GROUP BY entity_id
    """)
    rows = cur.fetchall()
    return {r["entity_id"]: r["first_signal_date"] for r in rows}


# ---------------------------------------------------------------------------
# Step 2 — Aggregate creator→entity data
# ---------------------------------------------------------------------------

_AGGREGATE_SQL = """
WITH base AS (
    SELECT
        cci.source_platform                                             AS platform,
        cci.source_account_id                                           AS creator_id,
        MAX(cci.source_account_handle)                                  AS creator_handle,
        em.entity_id::text                                              AS entity_id,
        em.entity_type                                                  AS entity_type,
        MAX(emarket.canonical_name)                                     AS canonical_name,
        MAX(emarket.brand_name)                                         AS brand_name,
        COUNT(*)                                                        AS mention_count,
        COUNT(DISTINCT cci.id)                                          AS unique_content_count,
        MIN(cci.published_at::date)                                     AS first_mention_date,
        MAX(cci.published_at::date)                                     AS last_mention_date,
        COALESCE(SUM(
            CASE WHEN (cci.engagement_json::jsonb->>'views') ~ '^[0-9]+$'
                 THEN (cci.engagement_json::jsonb->>'views')::bigint
                 ELSE 0 END
        ), 0)                                                           AS total_views,
        AVG(
            CASE WHEN (cci.engagement_json::jsonb->>'views') ~ '^[0-9]+$'
                      AND (cci.engagement_json::jsonb->>'views')::float > 0
                 THEN (cci.engagement_json::jsonb->>'views')::float
                 ELSE NULL END
        )                                                               AS avg_views,
        COALESCE(SUM(
            CASE WHEN (cci.engagement_json::jsonb->>'likes') ~ '^[0-9]+$'
                 THEN (cci.engagement_json::jsonb->>'likes')::bigint
                 ELSE 0 END
        ), 0)                                                           AS total_likes,
        COALESCE(SUM(
            CASE WHEN (cci.engagement_json::jsonb->>'comments') ~ '^[0-9]+$'
                 THEN (cci.engagement_json::jsonb->>'comments')::bigint
                 ELSE 0 END
        ), 0)                                                           AS total_comments
    FROM entity_mentions em
    JOIN canonical_content_items cci
        ON (cci.source_url = em.source_url OR cci.id = em.source_url)
    LEFT JOIN entity_market emarket
        ON emarket.id = em.entity_id
    WHERE cci.source_platform = 'youtube'
      AND cci.source_account_id IS NOT NULL
      AND cci.source_account_id ~ '^UC[a-zA-Z0-9_\-]{{22}}$'
      AND em.entity_id IS NOT NULL
    GROUP BY cci.source_platform, cci.source_account_id, em.entity_id::text, em.entity_type
),
engagement_from_sources AS (
    -- avg engagement rate from mention_sources (more reliable)
    SELECT
        ms.source_id                        AS creator_id,
        em.entity_id::text                  AS entity_id,
        AVG(ms.engagement_rate)             AS avg_engagement_rate
    FROM mention_sources ms
    JOIN entity_mentions em ON em.id = ms.mention_id
    WHERE ms.platform = 'youtube'
      AND ms.engagement_rate IS NOT NULL
    GROUP BY ms.source_id, em.entity_id::text
)
SELECT
    b.platform,
    b.creator_id,
    b.creator_handle,
    b.entity_id,
    b.entity_type,
    b.canonical_name,
    b.brand_name,
    b.mention_count,
    b.unique_content_count,
    b.first_mention_date,
    b.last_mention_date,
    b.total_views,
    b.avg_views,
    b.total_likes,
    b.total_comments,
    COALESCE(
        efs.avg_engagement_rate,
        CASE
            WHEN b.total_views > 0
            THEN (b.total_likes + b.total_comments)::float / b.total_views
            ELSE NULL
        END
    ) AS avg_engagement_rate
FROM base b
LEFT JOIN engagement_from_sources efs
    ON efs.creator_id = b.creator_id AND efs.entity_id = b.entity_id
{limit_clause}
"""

_UPSERT_SQL = """
INSERT INTO creator_entity_relationships (
    platform, creator_id, creator_handle,
    entity_id, entity_type, canonical_name, brand_name,
    mention_count, unique_content_count,
    first_mention_date, last_mention_date,
    total_views, avg_views, total_likes, total_comments,
    avg_engagement_rate,
    mentions_before_first_breakout, days_before_first_breakout,
    computed_at
) VALUES (
    %(platform)s, %(creator_id)s, %(creator_handle)s,
    %(entity_id)s, %(entity_type)s, %(canonical_name)s, %(brand_name)s,
    %(mention_count)s, %(unique_content_count)s,
    %(first_mention_date)s, %(last_mention_date)s,
    %(total_views)s, %(avg_views)s, %(total_likes)s, %(total_comments)s,
    %(avg_engagement_rate)s,
    %(mentions_before_first_breakout)s, %(days_before_first_breakout)s,
    %(computed_at)s
)
ON CONFLICT (platform, creator_id, entity_id)
DO UPDATE SET
    creator_handle              = EXCLUDED.creator_handle,
    entity_type                 = EXCLUDED.entity_type,
    canonical_name              = EXCLUDED.canonical_name,
    brand_name                  = EXCLUDED.brand_name,
    mention_count               = EXCLUDED.mention_count,
    unique_content_count        = EXCLUDED.unique_content_count,
    first_mention_date          = EXCLUDED.first_mention_date,
    last_mention_date           = EXCLUDED.last_mention_date,
    total_views                 = EXCLUDED.total_views,
    avg_views                   = EXCLUDED.avg_views,
    total_likes                 = EXCLUDED.total_likes,
    total_comments              = EXCLUDED.total_comments,
    avg_engagement_rate         = EXCLUDED.avg_engagement_rate,
    mentions_before_first_breakout = EXCLUDED.mentions_before_first_breakout,
    days_before_first_breakout  = EXCLUDED.days_before_first_breakout,
    computed_at                 = EXCLUDED.computed_at
"""


def _compute_early_signal(row: dict, first_signals: dict[str, datetime]) -> tuple[int, int | None]:
    """Return (mentions_before_first_breakout, days_before_first_breakout)."""
    entity_id = row["entity_id"]
    first_signal_dt = first_signals.get(entity_id)
    if not first_signal_dt:
        return 0, None

    first_signal_date = first_signal_dt.date()
    first_mention = row["first_mention_date"]
    last_mention = row["last_mention_date"]

    if not first_mention:
        return 0, None

    # Was the creator's first mention BEFORE the first breakout signal?
    if first_mention >= first_signal_date:
        return 0, None  # creator appeared after or same day as signal

    # Count: mentions_before_first_breakout
    # We approximate using the fact that this creator mentioned the entity
    # at some point before the first signal. We'll use 1 as a conservative
    # lower bound (at minimum the first mention counts); full per-item count
    # would require per-content-item date data. Use unique_content_count as proxy
    # capped by number of days of activity before first signal.
    days_before = (first_signal_date - first_mention).days
    return 1, days_before  # 1 = at least one early mention confirmed


def run(dry_run: bool, limit: int | None):
    conn = _get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        log.info("Loading first breakout/acceleration_spike signals per entity...")
        first_signals = _load_first_signals(cur)
        log.info("  Loaded %d entities with breakout/acceleration signals", len(first_signals))

        limit_clause = f"LIMIT {limit}" if limit else ""
        sql = _AGGREGATE_SQL.format(limit_clause=limit_clause)

        log.info("Running creator→entity aggregation query...")
        cur.execute(sql)
        rows = cur.fetchall()
        log.info("  Aggregated %d creator→entity relationships", len(rows))

        if dry_run:
            log.info("[DRY-RUN] Would upsert %d rows to creator_entity_relationships", len(rows))
            # Show sample
            log.info("Sample rows (first 5):")
            for r in rows[:5]:
                mbf, dbf = _compute_early_signal(dict(r), first_signals)
                log.info(
                    "  creator=%s entity=%s (%s) mentions=%d views=%d early_signal=%d",
                    r["creator_id"][:20],
                    r["entity_id"][:8],
                    r["canonical_name"] or "?",
                    r["mention_count"],
                    r["total_views"] or 0,
                    mbf,
                )
            return

        # Apply
        now = datetime.now(timezone.utc)
        batch = []
        total_upserted = 0

        for r in rows:
            rd = dict(r)
            mbf, dbf = _compute_early_signal(rd, first_signals)
            rd["mentions_before_first_breakout"] = mbf
            rd["days_before_first_breakout"] = dbf
            rd["computed_at"] = now
            batch.append(rd)

            if len(batch) >= _UPSERT_BATCH:
                cur_plain = conn.cursor()
                psycopg2.extras.execute_batch(cur_plain, _UPSERT_SQL, batch, page_size=_UPSERT_BATCH)
                conn.commit()
                total_upserted += len(batch)
                log.info("  Upserted %d rows (total so far: %d)", len(batch), total_upserted)
                batch = []

        if batch:
            cur_plain = conn.cursor()
            psycopg2.extras.execute_batch(cur_plain, _UPSERT_SQL, batch, page_size=_UPSERT_BATCH)
            conn.commit()
            total_upserted += len(batch)

        log.info("[DONE] Upserted %d creator_entity_relationships rows", total_upserted)

    finally:
        conn.close()


def verify():
    conn = _get_conn()
    try:
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM creator_entity_relationships")
        total = cur.fetchone()[0]
        log.info("creator_entity_relationships total rows: %d", total)

        cur.execute("SELECT COUNT(DISTINCT creator_id) FROM creator_entity_relationships WHERE platform='youtube'")
        creators = cur.fetchone()[0]
        log.info("Unique YouTube creators: %d", creators)

        cur.execute("SELECT COUNT(DISTINCT entity_id) FROM creator_entity_relationships WHERE platform='youtube'")
        entities = cur.fetchone()[0]
        log.info("Unique entities: %d", entities)

        cur.execute("""
            SELECT COUNT(*) FROM (
                SELECT platform, creator_id, entity_id
                FROM creator_entity_relationships
                GROUP BY platform, creator_id, entity_id
                HAVING COUNT(*) > 1
            ) x
        """)
        dups = cur.fetchone()[0]
        log.info("Duplicate (platform, creator_id, entity_id) count: %d  [must be 0]", dups)

        cur.execute("""
            SELECT COUNT(*) FROM creator_entity_relationships
            WHERE mentions_before_first_breakout > 0
        """)
        early = cur.fetchone()[0]
        log.info("Rows with early signal (mentions_before_first_breakout > 0): %d", early)

        log.info("\nTop 10 creator/entity pairs by mention_count:")
        cur.execute("""
            SELECT creator_id, creator_handle, canonical_name, mention_count, total_views
            FROM creator_entity_relationships
            ORDER BY mention_count DESC
            LIMIT 10
        """)
        for r in cur.fetchall():
            log.info("  %s (%s) → %s  mentions=%d  views=%d",
                     r[0][:20], r[1] or "?", r[2] or "?", r[3], r[4] or 0)

        log.info("\nTop 10 creator/entity pairs by total_views:")
        cur.execute("""
            SELECT creator_id, creator_handle, canonical_name, mention_count, total_views
            FROM creator_entity_relationships
            WHERE total_views > 0
            ORDER BY total_views DESC
            LIMIT 10
        """)
        for r in cur.fetchall():
            log.info("  %s (%s) → %s  mentions=%d  views=%d",
                     r[0][:20], r[1] or "?", r[2] or "?", r[3], r[4] or 0)

        log.info("\nTop 10 early-signal creators:")
        cur.execute("""
            SELECT creator_id, creator_handle, canonical_name,
                   mentions_before_first_breakout, days_before_first_breakout
            FROM creator_entity_relationships
            WHERE mentions_before_first_breakout > 0
            ORDER BY days_before_first_breakout DESC, mentions_before_first_breakout DESC
            LIMIT 10
        """)
        for r in cur.fetchall():
            log.info("  %s (%s) → %s  days_before=%s",
                     r[0][:20], r[1] or "?", r[2] or "?", r[4])

    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="C1.3 — compute creator_entity_relationships")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--apply", action="store_true", default=False)
    parser.add_argument("--limit", type=int, default=None, help="Limit rows processed")
    parser.add_argument("--verify", action="store_true", default=False)
    args = parser.parse_args()

    if args.verify:
        verify()
        return

    if not args.apply:
        # Default to dry-run
        args.dry_run = True

    run(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
