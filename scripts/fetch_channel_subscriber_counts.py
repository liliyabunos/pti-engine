#!/usr/bin/env python3
"""
C1.1 — Fetch YouTube channel subscriber/view/video counts and store in youtube_channels.

Uses YouTube Data API channels.list?part=statistics — 1 quota unit per 50 channels.
Only updates rows where subscriber_count IS NULL or subscriber_count_fetched_at IS NULL
(unless --force is passed).

Usage:
    python3 scripts/fetch_channel_subscriber_counts.py --dry-run
    python3 scripts/fetch_channel_subscriber_counts.py --apply
    python3 scripts/fetch_channel_subscriber_counts.py --apply --limit 50
    python3 scripts/fetch_channel_subscriber_counts.py --apply --force     # re-fetch all
    python3 scripts/fetch_channel_subscriber_counts.py --verify
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2
import psycopg2.extras
import requests


_BATCH_SIZE = 50  # max channel IDs per channels.list call (API limit)
_API_BASE = "https://www.googleapis.com/youtube/v3"
_SLEEP_BETWEEN_BATCHES = 0.5  # seconds


def _get_db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("[fetch_subscriber_counts] ERROR: DATABASE_URL not set.")
        sys.exit(1)
    return url


def _get_api_key() -> str:
    key = os.environ.get("YOUTUBE_API_KEY", "")
    if not key:
        print("[fetch_subscriber_counts] ERROR: YOUTUBE_API_KEY not set.")
        sys.exit(1)
    return key


def _load_channels(cur, force: bool, limit: Optional[int]) -> list[dict]:
    """Load channels that need subscriber_count populated."""
    if force:
        where = "WHERE status != 'blocked'"
    else:
        where = "WHERE (subscriber_count IS NULL OR subscriber_count_fetched_at IS NULL) AND status != 'blocked'"
    query = f"""
        SELECT channel_id, handle, title, quality_tier
        FROM youtube_channels
        {where}
        ORDER BY quality_tier ASC, added_at ASC
        {'LIMIT ' + str(limit) if limit else ''}
    """
    cur.execute(query)
    rows = cur.fetchall()
    return [
        {"channel_id": r[0], "handle": r[1], "title": r[2], "quality_tier": r[3]}
        for r in rows
    ]


def _fetch_stats_batch(channel_ids: list[str], api_key: str) -> dict[str, dict]:
    """
    Call channels.list for a batch of up to 50 channel IDs.
    Returns dict: channel_id -> {subscriber_count, video_count, view_count}.
    Hidden/private subscriber counts are returned as None.
    """
    ids_param = ",".join(channel_ids)
    resp = requests.get(
        f"{_API_BASE}/channels",
        params={
            "part": "statistics",
            "id": ids_param,
            "key": api_key,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    result: dict[str, dict] = {}
    for item in data.get("items", []):
        cid = item["id"]
        stats = item.get("statistics", {})
        # hiddenSubscriberCount=true means subscriber count is not public → store NULL
        hidden = stats.get("hiddenSubscriberCount", False)
        result[cid] = {
            "subscriber_count": None if hidden else _safe_int(stats.get("subscriberCount")),
            "video_count": _safe_int(stats.get("videoCount")),
            "view_count": _safe_int(stats.get("viewCount")),
        }
    return result


def _safe_int(val) -> Optional[int]:
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def run(dry_run: bool, force: bool, limit: Optional[int], verify: bool) -> None:
    db_url = _get_db_url()
    api_key = _get_api_key()

    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    cur = conn.cursor()

    if verify:
        cur.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN subscriber_count IS NOT NULL THEN 1 ELSE 0 END) AS with_sub,
                SUM(CASE WHEN subscriber_count_fetched_at IS NOT NULL THEN 1 ELSE 0 END) AS fetched_at_set,
                SUM(CASE WHEN subscriber_count IS NULL AND status != 'blocked' THEN 1 ELSE 0 END) AS still_missing
            FROM youtube_channels
        """)
        r = cur.fetchone()
        print(f"[verify] total={r[0]}  with_subscriber_count={r[1]}  fetched_at_set={r[2]}  still_missing={r[3]}")
        conn.close()
        return

    channels = _load_channels(cur, force=force, limit=limit)
    print(f"[fetch_subscriber_counts] channels to process: {len(channels)}")

    if not channels:
        print("[fetch_subscriber_counts] Nothing to do.")
        conn.close()
        return

    if dry_run:
        print("[fetch_subscriber_counts] dry_run=True — showing first 10 channels, no API calls, no DB writes")
        for ch in channels[:10]:
            print(f"  {ch['channel_id']}  {ch['handle'] or ch['title']}  tier={ch['quality_tier']}")
        conn.close()
        return

    # Batch into groups of _BATCH_SIZE
    batches = [channels[i:i + _BATCH_SIZE] for i in range(0, len(channels), _BATCH_SIZE)]
    updated = 0
    not_returned = 0
    api_errors = 0
    fetched_at = datetime.now(timezone.utc)

    for batch_idx, batch in enumerate(batches):
        ids = [ch["channel_id"] for ch in batch]
        print(f"  [batch {batch_idx + 1}/{len(batches)}] fetching {len(ids)} channels...")
        try:
            stats = _fetch_stats_batch(ids, api_key)
        except Exception as e:
            print(f"  [error] batch {batch_idx + 1} failed: {e!s:.120}")
            api_errors += 1
            time.sleep(2)
            continue

        for ch in batch:
            cid = ch["channel_id"]
            if cid not in stats:
                # Channel not returned by API — may be deleted or suspended
                not_returned += 1
                # Still mark as fetched so we don't retry endlessly
                cur.execute("""
                    UPDATE youtube_channels
                    SET subscriber_count_fetched_at = %s
                    WHERE channel_id = %s
                      AND subscriber_count_fetched_at IS NULL
                """, (fetched_at, cid))
                continue

            s = stats[cid]
            cur.execute("""
                UPDATE youtube_channels
                SET
                    subscriber_count = %s,
                    video_count = %s,
                    view_count = %s,
                    subscriber_count_fetched_at = %s
                WHERE channel_id = %s
            """, (
                s["subscriber_count"],
                s["video_count"],
                s["view_count"],
                fetched_at,
                cid,
            ))
            updated += 1

        conn.commit()
        if batch_idx < len(batches) - 1:
            time.sleep(_SLEEP_BETWEEN_BATCHES)

    print()
    print(f"[fetch_subscriber_counts] Complete.")
    print(f"  channels processed:   {len(channels)}")
    print(f"  updated in DB:        {updated}")
    print(f"  not returned by API:  {not_returned}")
    print(f"  batch API errors:     {api_errors}")

    # Summary
    cur.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN subscriber_count IS NOT NULL THEN 1 ELSE 0 END) AS with_sub,
            MIN(subscriber_count) FILTER (WHERE subscriber_count IS NOT NULL) AS min_sub,
            MAX(subscriber_count) FILTER (WHERE subscriber_count IS NOT NULL) AS max_sub,
            ROUND(AVG(subscriber_count) FILTER (WHERE subscriber_count IS NOT NULL)) AS avg_sub
        FROM youtube_channels
    """)
    r = cur.fetchone()
    print(f"  DB after: total={r[0]}  with_subscriber_count={r[1]}  "
          f"min={r[2]}  max={r[3]}  avg={r[4]}")

    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="C1.1 — Fetch YouTube channel subscriber counts (channels.list)"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Show channels to process, no API calls, no DB writes")
    parser.add_argument("--apply", action="store_true",
                        help="Execute API calls and write to DB")
    parser.add_argument("--force", action="store_true",
                        help="Re-fetch all channels, not just missing ones")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max channels to process (default: all)")
    parser.add_argument("--verify", action="store_true",
                        help="Print coverage stats only, no API calls")
    args = parser.parse_args()

    if not args.apply and not args.dry_run and not args.verify:
        print("Specify --dry-run, --apply, or --verify.")
        parser.print_help()
        sys.exit(1)

    run(
        dry_run=args.dry_run,
        force=args.force,
        limit=args.limit,
        verify=args.verify,
    )


if __name__ == "__main__":
    main()
