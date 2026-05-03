#!/usr/bin/env python3
"""
G3-C — YouTube Channel Auto-Discovery

Scans canonical_content_items for YouTube channels not yet in youtube_channels.
A channel qualifies as a discovery candidate when:
  - source_platform = 'youtube'
  - source_account_id is a valid UC... channel ID
  - NOT already in youtube_channels (LEFT JOIN anti-join)
  - >= min_videos videos found (default 2)
  - avg views >= min_avg_views (default 1000)
  - at least 1 video has at least 1 resolved entity OR resolved_entities_json length >= 1

Quality tier is auto-assigned from avg_views as a REACH PROXY, not a quality judgement:
  >= 50,000  → tier_2  (high reach — large audience)
  >=  5,000  → tier_3  (medium reach)
  <   5,000  → tier_4  (low reach / new channel)

This reflects estimated audience size at discovery time.
Actual channel quality (signal accuracy, entity resolution rate) must be confirmed
separately after polling — upgrade tier manually via manage_channels.py --update-tier
once resolved mentions and signal quality are observed.

All discovered channels start with:
  status   = 'active'
  category = 'unknown'
  priority = 'medium'
  added_by = 'g3_auto_discovery'

Usage:
  # Dry-run (default — no DB writes)
  python3 scripts/discover_youtube_channels.py

  # Real run — insert candidates
  python3 scripts/discover_youtube_channels.py --apply

  # Bounded run
  python3 scripts/discover_youtube_channels.py --apply --limit 50

  # Tighter view threshold
  python3 scripts/discover_youtube_channels.py --min-avg-views 5000 --apply

  # Require more videos
  python3 scripts/discover_youtube_channels.py --min-videos 3 --apply

Rollback:
  DELETE FROM youtube_channels WHERE added_by = 'g3_auto_discovery';
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Valid UC... channel ID format
_CHANNEL_ID_RE = re.compile(r"^UC[a-zA-Z0-9_-]{22}$")

# Auto-tier thresholds (based on avg video views)
_TIER_THRESHOLDS = [
    (50_000, "tier_2"),
    (5_000,  "tier_3"),
]
_TIER_FALLBACK = "tier_4"


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------

def _connect() -> psycopg2.extensions.connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("[error] DATABASE_URL not set. This script requires a Postgres connection.", file=sys.stderr)
        sys.exit(1)
    return psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auto_tier(avg_views: float | None) -> str:
    """
    Assign quality_tier based on average video views.

    This is a REACH PROXY, not a quality judgement.
    tier_2/tier_3/tier_4 here reflects estimated audience size at discovery time.
    Actual channel quality (resolved entities, signal accuracy) must be confirmed
    after polling — upgrade manually via manage_channels.py --update-tier.
    """
    if avg_views is None:
        return _TIER_FALLBACK
    for threshold, tier in _TIER_THRESHOLDS:
        if avg_views >= threshold:
            return tier
    return _TIER_FALLBACK


def _is_valid_channel_id(cid: str) -> bool:
    return bool(_CHANNEL_ID_RE.match(cid or ""))


# ---------------------------------------------------------------------------
# Discovery query
# ---------------------------------------------------------------------------

_DISCOVERY_SQL = """
WITH channel_stats AS (
    SELECT
        cci.source_account_id                                   AS channel_id,
        MAX(cci.source_account_handle)                          AS handle,
        COUNT(*)                                                AS videos_found,
        AVG(NULLIF((cci.engagement_json->>'views')::int, 0))    AS avg_views,
        SUM((cci.engagement_json->>'views')::int)               AS total_views,
        MAX(cci.title)                                          AS sample_title,
        MIN(cci.collected_at)                                   AS first_seen,
        MAX(cci.collected_at)                                   AS last_seen,
        -- Count videos where resolver produced at least one entity
        SUM(
            CASE
                WHEN rs.resolved_entities_json IS NOT NULL
                 AND rs.resolved_entities_json <> '[]'
                THEN 1 ELSE 0
            END
        )                                                       AS videos_with_entities
    FROM canonical_content_items cci
    LEFT JOIN youtube_channels yc
        ON yc.channel_id = cci.source_account_id
    LEFT JOIN resolved_signals rs
        ON rs.content_item_id = cci.id
    WHERE cci.source_platform = 'youtube'
      AND cci.source_account_id IS NOT NULL
      AND cci.source_account_id ~ '^UC[a-zA-Z0-9_\\-]{22}$'
      AND yc.channel_id IS NULL            -- anti-join: not already registered
    GROUP BY cci.source_account_id
    HAVING COUNT(*) >= %(min_videos)s
       AND AVG(NULLIF((cci.engagement_json->>'views')::int, 0)) >= %(min_avg_views)s
)
SELECT *
FROM channel_stats
ORDER BY avg_views DESC NULLS LAST, videos_found DESC
LIMIT %(limit)s;
"""


def _discover_candidates(
    conn: psycopg2.extensions.connection,
    min_videos: int,
    min_avg_views: int,
    limit: int,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(_DISCOVERY_SQL, {
            "min_videos": min_videos,
            "min_avg_views": min_avg_views,
            "limit": limit,
        })
        rows = cur.fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Insert
# ---------------------------------------------------------------------------

_INSERT_SQL = """
INSERT INTO youtube_channels (
    id, channel_id, handle, title, quality_tier, category,
    status, priority, added_at, added_by, notes
)
VALUES (
    %(id)s, %(channel_id)s, %(handle)s, %(title)s, %(quality_tier)s, 'unknown',
    'active', 'medium', NOW(), 'g3_auto_discovery', %(notes)s
)
ON CONFLICT (channel_id) DO NOTHING;
"""


def _insert_channel(
    conn: psycopg2.extensions.connection,
    row: dict[str, Any],
) -> bool:
    """Insert a discovered channel. Returns True if inserted, False if already existed."""
    avg_views = row.get("avg_views")
    quality_tier = _auto_tier(float(avg_views) if avg_views else None)

    avg_str = f"{float(avg_views):,.0f}" if avg_views else "n/a"
    notes = (
        f"auto-discovered: {row['videos_found']} vids, avg_views={avg_str} (reach proxy), "
        f"entities_in={row['videos_with_entities']}, "
        f"first_seen={str(row.get('first_seen', ''))[:10]}. "
        f"Tier reflects reach only — confirm quality after first poll."
    )

    with conn.cursor() as cur:
        cur.execute(_INSERT_SQL, {
            "id": str(uuid.uuid4()),
            "channel_id": row["channel_id"],
            "handle": row.get("handle"),
            "title": row.get("sample_title"),
            "quality_tier": quality_tier,
            "notes": notes,
        })
        inserted = cur.rowcount > 0
    return inserted


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def _verify(conn: psycopg2.extensions.connection) -> None:
    print("\n--- Verification ---")
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total FROM youtube_channels;")
        total = cur.fetchone()["total"]
        print(f"  youtube_channels total rows: {total}")

        cur.execute(
            "SELECT COUNT(*) AS g3 FROM youtube_channels WHERE added_by = 'g3_auto_discovery';"
        )
        g3 = cur.fetchone()["g3"]
        print(f"  g3_auto_discovery rows:      {g3}")

        cur.execute(
            """
            SELECT COUNT(*) AS dups
            FROM (
                SELECT channel_id, COUNT(*) AS c
                FROM youtube_channels
                GROUP BY channel_id
                HAVING COUNT(*) > 1
            ) x;
            """
        )
        dups = cur.fetchone()["dups"]
        print(f"  Duplicate channel_ids:       {dups}  (must be 0)")

        cur.execute(
            """
            SELECT quality_tier, COUNT(*) AS cnt
            FROM youtube_channels
            WHERE added_by = 'g3_auto_discovery'
            GROUP BY quality_tier
            ORDER BY quality_tier;
            """
        )
        print("\n  Tier breakdown (g3_auto_discovery):")
        for row in cur.fetchall():
            print(f"    {row['quality_tier']:10s} {row['cnt']}")

        cur.execute(
            """
            SELECT channel_id, handle, title, quality_tier, notes
            FROM youtube_channels
            WHERE added_by = 'g3_auto_discovery'
            ORDER BY added_at DESC
            LIMIT 25;
            """
        )
        print("\n  Sample (up to 25 most recent discovered):")
        print(f"  {'channel_id':<26}  {'handle':<30}  {'tier':<10}  title")
        print(f"  {'-'*26}  {'-'*30}  {'-'*10}  -----")
        for row in cur.fetchall():
            title = (row.get("title") or "")[:40]
            handle = (row.get("handle") or "")[:30]
            print(f"  {row['channel_id']:<26}  {handle:<30}  {row['quality_tier']:<10}  {title}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="G3-C — YouTube Channel Auto-Discovery",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write discovered channels to DB. Default: dry-run (no writes).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Max candidates to discover per run (default: 500).",
    )
    parser.add_argument(
        "--min-videos",
        type=int,
        default=2,
        help="Minimum number of videos a channel must have in canonical_content_items (default: 2).",
    )
    parser.add_argument(
        "--min-avg-views",
        type=int,
        default=1000,
        help="Minimum average view count per video (default: 1000).",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        default=False,
        help="Print verification stats after apply.",
    )
    args = parser.parse_args()

    dry_run = not args.apply

    conn = _connect()

    # Count existing channels before run
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total FROM youtube_channels;")
        before_total = cur.fetchone()["total"]
        cur.execute(
            "SELECT COUNT(*) AS g3 FROM youtube_channels WHERE added_by = 'g3_auto_discovery';"
        )
        before_g3 = cur.fetchone()["g3"]

    print(f"[discover] youtube_channels before: total={before_total}, g3_auto_discovery={before_g3}")
    print(f"[discover] params: min_videos={args.min_videos}, min_avg_views={args.min_avg_views:,}, limit={args.limit}")
    print(f"[discover] mode: {'DRY-RUN (no writes)' if dry_run else 'APPLY'}")
    print()

    # Discover
    candidates = _discover_candidates(
        conn,
        min_videos=args.min_videos,
        min_avg_views=args.min_avg_views,
        limit=args.limit,
    )

    if not candidates:
        print("[discover] No qualifying candidates found.")
        print(
            "  Possible reasons:\n"
            "    • All channels with enough videos already registered\n"
            "    • No channel meets avg_views threshold\n"
            "    • Increase --limit or lower --min-avg-views / --min-videos"
        )
        conn.close()
        return

    print(f"[discover] Found {len(candidates)} candidate(s):\n")
    print(f"  {'#':<4}  {'channel_id':<26}  {'handle':<30}  {'vids':>5}  {'avg_views':>10}  {'entities':>8}  {'tier':<10}  sample_title")
    print(f"  {'-'*4}  {'-'*26}  {'-'*30}  {'-'*5}  {'-'*10}  {'-'*8}  {'-'*10}  -----------")

    for i, row in enumerate(candidates, 1):
        avg = row.get("avg_views")
        avg_str = f"{float(avg):>10,.0f}" if avg else f"{'n/a':>10}"
        tier = _auto_tier(float(avg) if avg else None)
        handle = (row.get("handle") or "")[:30]
        title = (row.get("sample_title") or "")[:45]
        print(
            f"  {i:<4}  {row['channel_id']:<26}  {handle:<30}  "
            f"{row['videos_found']:>5}  {avg_str}  {row['videos_with_entities']:>8}  {tier:<10}  {title}"
        )

    print()

    if dry_run:
        print(f"[discover] DRY-RUN: {len(candidates)} channels would be inserted.")
        print("  Run with --apply to write to DB.")
        conn.close()
        return

    # Apply
    inserted = 0
    skipped = 0
    for row in candidates:
        ok = _insert_channel(conn, row)
        if ok:
            inserted += 1
        else:
            skipped += 1

    conn.commit()

    print(f"[discover] Applied: inserted={inserted}, skipped={skipped} (already existed)")

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total FROM youtube_channels;")
        after_total = cur.fetchone()["total"]
        cur.execute(
            "SELECT COUNT(*) AS g3 FROM youtube_channels WHERE added_by = 'g3_auto_discovery';"
        )
        after_g3 = cur.fetchone()["g3"]

    print(f"[discover] youtube_channels after: total={after_total}, g3_auto_discovery={after_g3}")
    print(f"[discover] Net new channels: +{after_total - before_total}")

    if args.verify:
        _verify(conn)

    print("\n[discover] Rollback if needed:")
    print("  DELETE FROM youtube_channels WHERE added_by = 'g3_auto_discovery';")

    conn.close()


if __name__ == "__main__":
    main()
