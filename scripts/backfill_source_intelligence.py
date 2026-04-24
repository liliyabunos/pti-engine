from __future__ import annotations

"""
Phase I1 — backfill source_profiles and mention_sources for existing entity_mentions.

Reads entity_mentions rows that have no corresponding mention_sources entry,
cross-references canonical_content_items to get raw engagement + channel metadata,
and creates missing mention_sources + source_profiles rows.

Idempotent: skips mention_ids that already exist in mention_sources.

Usage:
    python scripts/backfill_source_intelligence.py
    python scripts/backfill_source_intelligence.py --days 7 --dry-run
    python scripts/backfill_source_intelligence.py --days 30
"""

import argparse
import os
import sys
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from perfume_trend_sdk.storage.postgres.db import session_scope


def _engagement_rate(views: int, likes: int, comments: int) -> Optional[float]:
    return (likes + comments) / views if views > 0 else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def backfill(days: int = 7, dry_run: bool = False, batch_size: int = 200) -> dict:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("[backfill_source_intelligence] ERROR: DATABASE_URL not set.")
        sys.exit(1)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    print(f"[backfill_source_intelligence] days={days}  dry_run={dry_run}  cutoff={cutoff[:10]}")

    with session_scope() as db:
        # Find entity_mentions without mention_sources, within lookback window
        rows = db.execute(text("""
            SELECT
                em.id          AS mention_id,
                em.source_platform,
                em.author_id,
                em.source_url,
                cci.media_metadata_json,
                cci.engagement_json
            FROM entity_mentions em
            LEFT JOIN mention_sources ms ON ms.mention_id = em.id
            LEFT JOIN canonical_content_items cci ON (
                cci.id = em.source_url
                OR cci.source_url = em.source_url
            )
            WHERE ms.id IS NULL
              AND em.occurred_at >= :cutoff
            ORDER BY em.occurred_at DESC
            LIMIT 5000
        """), {"cutoff": cutoff}).fetchall()

        print(f"[backfill_source_intelligence] mentions without source data: {len(rows)}")

        profiles_upserted = 0
        sources_written = 0

        for i, row in enumerate(rows):
            mention_id = row[0]
            platform = row[1] or "unknown"
            author_id = row[2] or ""
            media_meta = json.loads(row[4] or "{}") if row[4] else {}
            engagement = json.loads(row[5] or "{}") if row[5] else {}

            source_id = media_meta.get("channel_id") or author_id
            source_name = media_meta.get("channel_title") or author_id

            views = int(engagement.get("views") or 0)
            likes = int(engagement.get("likes") or 0)
            comments = int(engagement.get("comments") or 0)
            eng_rate = _engagement_rate(views, likes, comments)

            if dry_run:
                if i < 5:
                    print(
                        f"  [dry] mention_id={mention_id} platform={platform} "
                        f"source={source_name} views={views} likes={likes}"
                    )
                continue

            try:
                # Use DO NOTHING in backfill — avoids UPDATE lock contention with live pipeline
                if source_id:
                    db.execute(text("""
                        INSERT INTO source_profiles
                            (id, platform, source_id, source_name, created_at, updated_at)
                        VALUES
                            (gen_random_uuid(), :platform, :source_id, :source_name, NOW(), NOW())
                        ON CONFLICT (platform, source_id) DO NOTHING
                    """), {
                        "platform": platform,
                        "source_id": source_id,
                        "source_name": source_name,
                    })
                    profiles_upserted += 1

                db.execute(text("""
                    INSERT INTO mention_sources
                        (id, mention_id, platform, source_id, source_name,
                         views, likes, comments_count, engagement_rate, created_at)
                    VALUES
                        (gen_random_uuid(), :mention_id, :platform, :source_id, :source_name,
                         :views, :likes, :comments_count, :engagement_rate, NOW())
                    ON CONFLICT (mention_id) DO NOTHING
                """), {
                    "mention_id": str(mention_id),
                    "platform": platform,
                    "source_id": source_id or "",
                    "source_name": source_name,
                    "views": views or None,
                    "likes": likes or None,
                    "comments_count": comments or None,
                    "engagement_rate": eng_rate,
                })
                sources_written += 1

            except Exception as row_exc:
                # Skip row on deadlock or transient error — backfill is idempotent
                db.rollback()
                print(f"  [skip] mention_id={mention_id} error={row_exc!s:.120}")
                continue

            # Batch commit
            if (i + 1) % batch_size == 0:
                db.commit()
                print(f"  [progress] {i + 1}/{len(rows)} processed")

        if not dry_run:
            db.commit()

    summary = {
        "mentions_found": len(rows),
        "profiles_upserted": profiles_upserted,
        "sources_written": sources_written,
        "dry_run": dry_run,
    }

    print()
    print(f"[backfill_source_intelligence] Complete.")
    print(f"  mentions found (no source data): {summary['mentions_found']}")
    if not dry_run:
        print(f"  source_profiles upserted:        {summary['profiles_upserted']}")
        print(f"  mention_sources written:         {summary['sources_written']}")
    else:
        print("  dry_run=True — no writes performed")

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill source intelligence for existing mentions")
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days (default: 7)")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no writes")
    args = parser.parse_args()
    backfill(days=args.days, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
