#!/usr/bin/env python3
"""
YT-CREATOR-EXPANSION-01 — Idempotent seed for verified ADD candidates.

Reads reports/youtube_candidate_add_2026-05-10.json and INSERTs each channel
into youtube_channels with ON CONFLICT (channel_id) DO NOTHING.

Usage:
    python3 scripts/youtube/seed_yt_creator_expansion_01.py [--dry-run] [--db-url URL]

Options:
    --dry-run     Print SQL without executing.
    --db-url URL  PostgreSQL URL (default: $DATABASE_URL or $DATABASE_PUBLIC_URL).
"""
import argparse
import json
import os
import sys
import uuid
from pathlib import Path

ADD_JSON = Path(__file__).parent.parent.parent / "reports" / "youtube_candidate_add_2026-05-10.json"

# Map priority by tier
_TIER_PRIORITY = {
    "tier_1": "high",
    "tier_2": "high",
    "tier_3": "medium",
    "tier_4": "low",
}


def uploads_playlist_id(channel_id: str) -> str:
    """UC... → UU..."""
    if channel_id.startswith("UC"):
        return "UU" + channel_id[2:]
    return channel_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db-url", default=None)
    args = parser.parse_args()

    db_url = args.db_url or os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")
    if not db_url and not args.dry_run:
        print("[error] No DB URL. Pass --db-url or export DATABASE_URL.", file=sys.stderr)
        sys.exit(1)

    candidates = json.loads(ADD_JSON.read_text())
    print(f"[seed] {len(candidates)} ADD candidates from {ADD_JSON.name}")

    if args.dry_run:
        print("[seed] DRY RUN — no DB writes")

    inserted = 0
    skipped = 0

    if not args.dry_run:
        import psycopg2
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()

    for c in candidates:
        channel_id = c["channel_id"]
        title = (c.get("title") or "").strip()
        handle = c.get("handle") or None
        subscriber_count = c.get("subscriber_count")
        video_count = c.get("video_count")
        quality_tier = c.get("quality_tier", "tier_3")
        priority = _TIER_PRIORITY.get(quality_tier, "medium")
        uploads = uploads_playlist_id(channel_id)
        notes = f"YT-CREATOR-EXPANSION-01 | {c['candidate_name']} | {c['reason']}"
        row_id = str(uuid.uuid4())

        sql = """
INSERT INTO youtube_channels (
    id, channel_id, handle, channel_url, title, normalized_title,
    quality_tier, category, status, priority, subscriber_count, video_count,
    uploads_playlist_id, added_at, added_by, notes
) VALUES (
    %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s,
    %s, NOW(), %s, %s
)
ON CONFLICT (channel_id) DO NOTHING
""".strip()

        params = (
            row_id,
            channel_id,
            handle,
            f"https://www.youtube.com/channel/{channel_id}",
            title,
            title.lower(),
            quality_tier,
            "beauty",       # default category for fragrance creators
            "active",
            priority,
            subscriber_count,
            video_count,
            uploads,
            "yt_creator_expansion_01",
            notes,
        )

        if args.dry_run:
            print(f"  INSERT {channel_id} ({title}) [{quality_tier}] priority={priority}")
        else:
            cur.execute(sql, params)
            rows_affected = cur.rowcount
            if rows_affected == 1:
                inserted += 1
                print(f"  [inserted] {channel_id}  {title}")
            else:
                skipped += 1
                print(f"  [skipped]  {channel_id}  {title}  (already exists)")

    if not args.dry_run:
        conn.commit()
        conn.close()
        print(f"\n[seed] Done — inserted={inserted}  skipped={skipped}")
    else:
        print(f"\n[seed] DRY RUN complete — {len(candidates)} rows would be inserted")


if __name__ == "__main__":
    main()
