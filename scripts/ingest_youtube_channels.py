#!/usr/bin/env python3
"""
YouTube Channel-First Ingestion — Phase 1B.

Polls registered channels (youtube_channels table) using playlistItems.list
instead of search.list, consuming ~23× fewer quota units.

Quota cost per run (approximate):
  channels.list     1 unit per channel (only when uploads_playlist_id unknown)
  playlistItems.list 1 unit per page (up to ceil(max_results/50) pages per channel)
  videos.list       1 unit per 50 videos (batch stats fetch)

Flow per channel:
  1. Read uploads_playlist_id from registry (or fetch via channels.list + cache it)
  2. Paginate playlistItems.list to collect recent video IDs
  3. Filter by published_after cutoff (client-side; API does not support this natively)
  4. Fetch stats in batches (videos.list)
  5. Normalize → resolve → store (same path as search-based ingestion)
  6. Update youtube_channels row: last_polled_at, last_video_count, poll_status, error

Usage:
  # Dry-run (no DB writes, no API calls to resolve/store)
  python3 scripts/ingest_youtube_channels.py --dry-run --limit 5

  # Poll first 20 channels ordered by last_polled_at NULLS FIRST
  python3 scripts/ingest_youtube_channels.py --limit 20 --max-results 50

  # Poll only tier_1 high-priority channels
  python3 scripts/ingest_youtube_channels.py --quality-tier tier_1 --priority high

  # Use a longer lookback for channels not polled in a while
  python3 scripts/ingest_youtube_channels.py --first-poll-lookback-days 90 --lookback-days 3
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2
import psycopg2.extras

from perfume_trend_sdk.connectors.youtube.client import YouTubeClient
from perfume_trend_sdk.normalizers.social_content.normalizer import SocialContentNormalizer
from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import make_resolver
from perfume_trend_sdk.storage.normalized.pg_store import PgNormalizedContentStore
from perfume_trend_sdk.storage.normalized.sqlite_store import NormalizedContentStore
from perfume_trend_sdk.storage.raw.filesystem import FilesystemRawStorage
from perfume_trend_sdk.storage.signals.pg_store import PgSignalStore
from perfume_trend_sdk.storage.signals.sqlite_store import SignalStore
from perfume_trend_sdk.analysis.source_intelligence.analyzer import classify_source
from perfume_trend_sdk.analysis.source_intelligence.scoring import compute_influence
from perfume_trend_sdk.storage.entities.candidate_store import batch_upsert_candidates
from perfume_trend_sdk.storage.postgres.db import session_scope


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso_days_ago(days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_id(channel_id: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"yt_channel_{channel_id}_{ts}"


def _make_stores(market_db: str):
    database_url = os.environ.get("DATABASE_URL", "")
    if database_url:
        return PgNormalizedContentStore(database_url), PgSignalStore(database_url)
    ns = NormalizedContentStore(market_db)
    ss = SignalStore(market_db)
    ns.init_schema()
    ss.init_schema()
    return ns, ss


def _pg_connect() -> psycopg2.extensions.connection:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("[error] DATABASE_URL not set. Cannot read youtube_channels table.", file=sys.stderr)
        sys.exit(1)
    return psycopg2.connect(database_url)


def _load_channels(
    conn: psycopg2.extensions.connection,
    *,
    limit: int,
    offset: int,
    quality_tier: Optional[str],
    priority: Optional[str],
    status: str = "active",
) -> List[Dict[str, Any]]:
    """Load channels ordered by last_polled_at NULLS FIRST (unpolled first)."""
    clauses = ["status = %s"]
    params: list = [status]

    if quality_tier:
        clauses.append("quality_tier = %s")
        params.append(quality_tier)
    if priority:
        clauses.append("priority = %s")
        params.append(priority)

    where = " AND ".join(clauses)
    params.extend([limit, offset])

    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(
            f"""
            SELECT id, channel_id, title, quality_tier, category, priority,
                   uploads_playlist_id, last_polled_at, consecutive_empty_polls
            FROM youtube_channels
            WHERE {where}
            ORDER BY last_polled_at NULLS FIRST, priority DESC, added_at
            LIMIT %s OFFSET %s
            """,
            params,
        )
        return [dict(r) for r in cur.fetchall()]


def _update_channel_after_poll(
    conn: psycopg2.extensions.connection,
    channel_id: str,
    *,
    uploads_playlist_id: Optional[str] = None,
    last_video_count: int = 0,
    consecutive_empty_polls: int = 0,
    status: str = "ok",
    error: Optional[str] = None,
) -> None:
    fields = [
        "last_polled_at = NOW()",
        "last_video_count = %s",
        "consecutive_empty_polls = %s",
        "last_poll_status = %s",
        "last_poll_error = %s",
    ]
    params: list = [last_video_count, consecutive_empty_polls, status, error]

    if uploads_playlist_id is not None:
        fields.append("uploads_playlist_id = %s")
        params.append(uploads_playlist_id)

    params.append(channel_id)

    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE youtube_channels SET {', '.join(fields)} WHERE channel_id = %s",
            params,
        )
    conn.commit()


def _fetch_playlist_videos(
    client: YouTubeClient,
    playlist_id: str,
    *,
    published_after_iso: str,
    max_results: int,
) -> List[Dict[str, Any]]:
    """
    Paginate playlistItems.list and return raw snippet items published after the cutoff.
    Stops early when it encounters items older than published_after_iso.
    """
    collected: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    cutoff_dt = datetime.fromisoformat(published_after_iso.replace("Z", "+00:00"))

    while len(collected) < max_results:
        batch_size = min(50, max_results - len(collected))
        payload = client.list_channel_uploads(
            playlist_id,
            max_results=batch_size,
            page_token=page_token,
        )

        items = payload.get("items", [])
        if not items:
            break

        hit_cutoff = False
        for item in items:
            published_at_str = item.get("snippet", {}).get("publishedAt", "")
            if not published_at_str:
                continue
            published_dt = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
            if published_dt < cutoff_dt:
                hit_cutoff = True
                break
            collected.append(item)

        if hit_cutoff:
            break

        page_token = payload.get("nextPageToken")
        if not page_token:
            break

    return collected


def _playlist_item_to_search_item(snippet: Dict[str, Any], video_id: str) -> Dict[str, Any]:
    """Reshape a playlistItems snippet into the same shape as a search.list item,
    so the existing normalizer can process it unchanged."""
    return {
        "id": {"kind": "youtube#video", "videoId": video_id},
        "snippet": {
            "publishedAt": snippet.get("publishedAt", ""),
            "channelId": snippet.get("channelId", ""),
            "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "channelTitle": snippet.get("channelTitle", ""),
            "resourceId": snippet.get("resourceId", {}),
        },
    }


# ---------------------------------------------------------------------------
# Core polling loop
# ---------------------------------------------------------------------------

def poll_channel(
    channel: Dict[str, Any],
    *,
    client: YouTubeClient,
    normalizer: SocialContentNormalizer,
    normalized_store,
    signal_store,
    resolver,
    raw_storage: FilesystemRawStorage,
    conn: psycopg2.extensions.connection,
    lookback_days: int,
    first_poll_lookback_days: int,
    max_results: int,
    dry_run: bool,
) -> Dict[str, Any]:
    channel_id = channel["channel_id"]
    title = channel.get("title") or channel_id

    # Choose lookback window
    if channel.get("last_polled_at") is None:
        effective_lookback = first_poll_lookback_days
    else:
        effective_lookback = lookback_days

    published_after = _iso_days_ago(effective_lookback)

    print(f"  [channel] {channel_id}  {title[:50]!r}  lookback={effective_lookback}d")

    if dry_run:
        print(f"    [dry-run] would poll uploads_playlist_id, fetch videos, normalize, resolve")
        return {"channel_id": channel_id, "status": "dry_run", "video_count": 0}

    try:
        # Step 1: Resolve uploads_playlist_id (cache it if not already stored)
        playlist_id = channel.get("uploads_playlist_id")
        if not playlist_id:
            playlist_id = client.get_uploads_playlist_id(channel_id)
            if not playlist_id:
                print(f"    [warn] Could not get uploads_playlist_id — channel may be private or deleted.")
                _update_channel_after_poll(
                    conn, channel_id,
                    status="error",
                    error="uploads_playlist_id unavailable",
                    consecutive_empty_polls=channel.get("consecutive_empty_polls", 0) + 1,
                )
                return {"channel_id": channel_id, "status": "error", "video_count": 0}

        # Step 2: Fetch recent playlist items
        playlist_items = _fetch_playlist_videos(
            client,
            playlist_id,
            published_after_iso=published_after,
            max_results=max_results,
        )

        if not playlist_items:
            new_empty_count = channel.get("consecutive_empty_polls", 0) + 1
            print(f"    [info] no new videos in window (empty_polls={new_empty_count})")
            _update_channel_after_poll(
                conn, channel_id,
                uploads_playlist_id=playlist_id,
                last_video_count=0,
                consecutive_empty_polls=new_empty_count,
                status="ok",
            )
            return {"channel_id": channel_id, "status": "empty", "video_count": 0}

        # Step 3: Extract video IDs and reshape into normalizer-compatible format
        video_ids = []
        search_shaped_items = []
        for item in playlist_items:
            vid_id = item["snippet"]["resourceId"]["videoId"]
            video_ids.append(vid_id)
            search_shaped_items.append(_playlist_item_to_search_item(item["snippet"], vid_id))

        # Step 4: Fetch stats (batch)
        stats_map = client.fetch_video_stats(video_ids)

        # Merge stats into shaped items (same format as connector)
        raw_items = []
        for shaped, vid_id in zip(search_shaped_items, video_ids):
            stats = stats_map.get(vid_id, {})
            merged = {**shaped}
            if stats:
                merged["statistics"] = stats.get("statistics", {})
                merged["contentDetails"] = stats.get("contentDetails", {})
            raw_items.append(merged)

        # Step 5: Store raw + normalize
        run_id = _run_id(channel_id)
        raw_refs = raw_storage.save_raw_batch("youtube", run_id, raw_items)

        normalized_items = []
        for raw_item, raw_ref in zip(raw_items, raw_refs):
            n = normalizer.normalize_youtube_item(raw_item, raw_payload_ref=raw_ref)
            # Tag with channel ingestion method
            n["ingestion_method"] = "channel_poll"
            n["media_metadata"]["source_type"] = classify_source(n)
            n["media_metadata"]["influence_score"] = compute_influence(n)
            normalized_items.append(n)

        normalized_store.save_content_items(normalized_items)

        # Step 6: Resolve
        resolved_items = [resolver.resolve_content_item(item) for item in normalized_items]
        signal_store.save_resolved_signals(resolved_items)

        with session_scope() as db:
            batch_upsert_candidates(db, resolved_items, source_platform="youtube")

        entities_found = sum(len(r.get("resolved_entities", [])) for r in resolved_items)

        print(f"    [ok] {len(video_ids)} videos → {entities_found} entity links")

        _update_channel_after_poll(
            conn, channel_id,
            uploads_playlist_id=playlist_id,
            last_video_count=len(video_ids),
            consecutive_empty_polls=0,
            status="ok",
        )

        return {"channel_id": channel_id, "status": "ok", "video_count": len(video_ids)}

    except Exception as exc:
        error_msg = str(exc)[:500]
        print(f"    [error] {error_msg}")
        _update_channel_after_poll(
            conn, channel_id,
            consecutive_empty_polls=channel.get("consecutive_empty_polls", 0) + 1,
            status="error",
            error=error_msg,
        )
        return {"channel_id": channel_id, "status": "error", "video_count": 0}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="YouTube channel-first ingestion (Phase 1B)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--limit", type=int, default=50,
        help="Max number of channels to poll per run (default: 50)"
    )
    parser.add_argument(
        "--offset", type=int, default=0,
        help="Skip the first N channels (for manual pagination)"
    )
    parser.add_argument(
        "--max-results", type=int, default=50,
        help="Max videos to fetch per channel per run (default: 50)"
    )
    parser.add_argument(
        "--lookback-days", type=int, default=3,
        help="For channels already polled: look back N days (default: 3)"
    )
    parser.add_argument(
        "--first-poll-lookback-days", type=int, default=30,
        help="For channels never polled: look back N days on first run (default: 30)"
    )
    parser.add_argument(
        "--quality-tier",
        choices=["tier_1", "tier_2", "tier_3", "tier_4", "unrated"],
        help="Only poll channels of this quality tier"
    )
    parser.add_argument(
        "--priority",
        choices=["high", "medium", "low"],
        help="Only poll channels of this priority"
    )
    parser.add_argument(
        "--status", default="active",
        help="Channel status filter (default: active)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be done without making API or DB writes"
    )
    parser.add_argument(
        "--market-db", default=os.environ.get("PTI_DB_PATH", "outputs/market_dev.db"),
        help="Market engine SQLite DB path (ignored when DATABASE_URL is set)"
    )
    parser.add_argument(
        "--resolver-db", default="outputs/pti.db",
        help="Resolver SQLite DB path (ignored when DATABASE_URL is set)"
    )
    parser.add_argument(
        "--raw-dir", default="data/raw/youtube",
        help="Directory for raw payload storage"
    )
    args = parser.parse_args()

    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("[error] YOUTUBE_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    print(f"[ingest_youtube_channels] dry_run={args.dry_run}")
    print(f"[ingest_youtube_channels] limit={args.limit}  offset={args.offset}")
    print(f"[ingest_youtube_channels] max_results={args.max_results}")
    print(f"[ingest_youtube_channels] lookback={args.lookback_days}d  first_poll={args.first_poll_lookback_days}d")
    if args.quality_tier:
        print(f"[ingest_youtube_channels] quality_tier={args.quality_tier}")
    if args.priority:
        print(f"[ingest_youtube_channels] priority={args.priority}")

    conn = _pg_connect()
    channels = _load_channels(
        conn,
        limit=args.limit,
        offset=args.offset,
        quality_tier=args.quality_tier,
        priority=args.priority,
        status=args.status,
    )

    if not channels:
        print("[ingest_youtube_channels] No channels found matching filters. Exiting.")
        conn.close()
        return

    print(f"[ingest_youtube_channels] channels to poll: {len(channels)}\n")

    client = YouTubeClient(api_key=api_key)
    normalizer = SocialContentNormalizer()
    raw_storage = FilesystemRawStorage(base_dir=args.raw_dir)
    normalized_store, signal_store = _make_stores(args.market_db)
    resolver = make_resolver(args.resolver_db)
    resolver.store.init_schema()

    results = []
    for channel in channels:
        result = poll_channel(
            channel,
            client=client,
            normalizer=normalizer,
            normalized_store=normalized_store,
            signal_store=signal_store,
            resolver=resolver,
            raw_storage=raw_storage,
            conn=conn,
            lookback_days=args.lookback_days,
            first_poll_lookback_days=args.first_poll_lookback_days,
            max_results=args.max_results,
            dry_run=args.dry_run,
        )
        results.append(result)

    conn.close()

    ok = sum(1 for r in results if r["status"] == "ok")
    empty = sum(1 for r in results if r["status"] == "empty")
    errors = sum(1 for r in results if r["status"] == "error")
    dry = sum(1 for r in results if r["status"] == "dry_run")
    total_videos = sum(r.get("video_count", 0) for r in results)

    print()
    print("=" * 60)
    print(f"[ingest_youtube_channels] Done.")
    print(f"  channels polled: {len(results)}")
    print(f"  ok:              {ok}")
    print(f"  empty:           {empty}")
    print(f"  errors:          {errors}")
    if dry:
        print(f"  dry_run:         {dry}")
    print(f"  total videos:    {total_videos}")
    print("=" * 60)


if __name__ == "__main__":
    main()
