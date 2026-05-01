#!/usr/bin/env python3
"""
YouTube Channel-First Ingestion — Phase 1B / Phase 1C (adaptive polling).

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
import re
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


def _compute_next_poll_after(
    last_video_count: int,
    consecutive_empty_polls: int,
    quality_tier: str,
) -> datetime:
    """Return the UTC datetime after which this channel should next be polled.

    Interval table (evaluated top-to-bottom, first match wins):
      consecutive_empty_polls >= 14  →  168 h  (7 days)
      consecutive_empty_polls >= 7   →   72 h  (3 days)
      consecutive_empty_polls >= 3   →   48 h  (2 days)
      last_video_count >= 3 AND consecutive_empty_polls == 0  →  12 h
      otherwise                      →   24 h

    Tier floors (cap the interval — prevent high-value channels from going dark):
      tier_1  →  max 24 h
      tier_2  →  max 72 h
      tier_3 / tier_4 / unrated  →  no floor (trust the backoff)
    """
    if consecutive_empty_polls >= 14:
        hours = 168
    elif consecutive_empty_polls >= 7:
        hours = 72
    elif consecutive_empty_polls >= 3:
        hours = 48
    elif last_video_count >= 3 and consecutive_empty_polls == 0:
        hours = 12
    else:
        hours = 24

    # Tier floor — prevent backoff beyond the tier ceiling
    if quality_tier == "tier_1":
        hours = min(hours, 24)
    elif quality_tier == "tier_2":
        hours = min(hours, 72)
    # tier_3 / tier_4 / unrated: no cap

    return datetime.now(timezone.utc) + timedelta(hours=hours)


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
    skip_not_due: bool = True,
) -> List[Dict[str, Any]]:
    """Load channels that are due for polling, ordered by last_polled_at NULLS FIRST.

    Due-channel filter (when skip_not_due=True, the default):
      next_poll_after IS NULL        — never polled, always eligible
      OR next_poll_after <= NOW()    — computed due time has passed

    Channels with next_poll_after in the future are skipped — they already
    received a fresh poll and should not be re-polled until the interval elapses.
    """
    clauses = ["status = %s"]
    params: list = [status]

    if skip_not_due:
        clauses.append("(next_poll_after IS NULL OR next_poll_after <= NOW())")

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
                   uploads_playlist_id, last_polled_at, consecutive_empty_polls,
                   next_poll_after
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
    next_poll_after: Optional[datetime] = None,
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

    if next_poll_after is not None:
        fields.append("next_poll_after = %s")
        params.append(next_poll_after)

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
# Transcript queue logic
# ---------------------------------------------------------------------------

# Terms that signal a video is likely about fragrances.
# Case-insensitive substring match on title + description.
_FRAGRANCE_TERMS = frozenset([
    "fragrance", "perfume", "cologne", "parfum", "scent",
    "eau de parfum", "edp", "edt", "eau de toilette", "extrait",
    "oud", "musk", "ambergris",
    "niche fragrance", "designer fragrance",
    "blind buy", "dupe", "clone",
    "fragrance review", "perfume review", "cologne review",
    "best fragrance", "best perfume", "top fragrance",
    "compliment", "longevity", "projection", "sillage",
    "fragrance collection", "perfume collection",
    "baccarat rouge", "creed aventus", "dior sauvage",
    "fragranceone", "fragrance one",   # Jeremy's brand
    "#fragrance", "#perfume", "#cologne",
])

# Tiers that automatically qualify for transcript extraction.
_HIGH_PRIORITY_TIERS = frozenset(["tier_1", "tier_2"])

# Categories that automatically qualify.
_HIGH_PRIORITY_CATEGORIES = frozenset(["reviewer"])

# URL pattern — matches http:// and https:// links including query strings.
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def _text_without_urls(s: str) -> str:
    """Strip all http/https URLs from a string before term matching.

    Prevents boilerplate footer links (e.g. https://example.com/fragrance-shop)
    from triggering a fragrance-context match on non-fragrance content.
    """
    return _URL_RE.sub(" ", s)


def _is_short(raw_item: Dict[str, Any]) -> bool:
    """Return True if the video is a YouTube Short (≤ 60 seconds)."""
    details = raw_item.get("video_details", {})
    duration = details.get("contentDetails", {}).get("duration", "")
    # ISO 8601 duration: PT30S, PT1M, PT10M30S, etc.
    # Shorts are always < 1 minute (no M component, only S).
    if not duration:
        return False
    if "M" in duration:
        return False   # at least 1 minute — not a Short
    # Check for #Shorts tag in title/description as a fallback signal
    snippet = raw_item.get("search_item", {}).get("snippet", {})
    title = snippet.get("title", "").lower()
    desc = snippet.get("description", "").lower()
    if "#shorts" in title or "#shorts" in desc:
        return True
    # Pure seconds only — almost certainly a Short
    return True


def _has_fragrance_context(raw_item: Dict[str, Any]) -> bool:
    """Return True if title or description (minus URLs) contains a fragrance term.

    URLs are stripped first so boilerplate footer links containing the word
    'fragrance' (e.g. https://example.com/accessories-fragrance01) do not
    trigger a false positive on non-fragrance videos.
    """
    snippet = raw_item.get("search_item", {}).get("snippet", {})
    raw_text = snippet.get("title", "") + " " + snippet.get("description", "")
    combined = _text_without_urls(raw_text).lower()
    return any(term in combined for term in _FRAGRANCE_TERMS)


def _classify_transcript_priority(
    raw_item: Dict[str, Any],
    channel: Dict[str, Any],
) -> tuple[str, str]:
    """
    Return (transcript_status, transcript_priority) for a single normalized item.

    Rules (evaluated in order — first match wins):
      1. Channel tier_1 or tier_2 → needed / high
      2. Channel category = reviewer → needed / high
      3. Video has fragrance context terms in title/description → needed / high
      4. Video is a Short (≤ 60 s) AND channel is a known fragrance creator
         (has ANY fragrance term in the channel title OR is already tier_1/tier_2) → needed / high
      5. Otherwise → none / none
    """
    quality_tier = channel.get("quality_tier", "unrated")
    category = channel.get("category", "unknown")

    if quality_tier in _HIGH_PRIORITY_TIERS:
        return "needed", "high"

    if category in _HIGH_PRIORITY_CATEGORIES:
        return "needed", "high"

    if _has_fragrance_context(raw_item):
        return "needed", "high"

    # Short from a channel whose title contains fragrance terms
    if _is_short(raw_item):
        ch_title = (channel.get("title") or "").lower()
        if any(t in ch_title for t in _FRAGRANCE_TERMS):
            return "needed", "high"

    return "none", "none"


# ---------------------------------------------------------------------------
# Resolver input gating — channel_poll uses title-only
# ---------------------------------------------------------------------------

def _resolver_input(item: Dict[str, Any]) -> Dict[str, Any]:
    """Return a resolver-ready copy of the item.

    For ``channel_poll`` ingestion the description is NOT used as resolver input.
    YouTube descriptions contain repeated channel-footer boilerplate (affiliate
    links, social handles, sponsor lines) that is identical across every video
    in a channel.  Common words and digit strings in these footers (e.g. "cologne",
    "Don", "11", "21" embedded in URLs) match perfume aliases and create false-
    positive ``resolved_signals`` rows for videos that have nothing to do with
    those entities.

    Fix: for ``channel_poll`` items, set ``text_content`` to the video title only.
    The full description remains stored in ``canonical_content_items`` for future
    transcript-based re-resolution (after ``fetch_transcripts.py`` runs and quality
    checks pass).

    For all other ingestion methods (``search``, ``api``, …) the item is returned
    unchanged so existing behaviour is not affected.
    """
    if item.get("ingestion_method") == "channel_poll":
        return {**item, "text_content": item.get("title") or ""}
    return item


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
                new_empty_count = channel.get("consecutive_empty_polls", 0) + 1
                _update_channel_after_poll(
                    conn, channel_id,
                    status="error",
                    error="uploads_playlist_id unavailable",
                    consecutive_empty_polls=new_empty_count,
                    next_poll_after=_compute_next_poll_after(
                        0, new_empty_count, channel.get("quality_tier", "unrated")
                    ),
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
            npa = _compute_next_poll_after(0, new_empty_count, channel.get("quality_tier", "unrated"))
            print(
                f"    [info] no new videos in window (empty_polls={new_empty_count},"
                f" next_poll_after={npa.isoformat()})"
            )
            _update_channel_after_poll(
                conn, channel_id,
                uploads_playlist_id=playlist_id,
                last_video_count=0,
                consecutive_empty_polls=new_empty_count,
                status="ok",
                next_poll_after=npa,
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

        # Wrap items in the same structure the normalizer expects:
        # {"search_item": <search-shaped item>, "video_details": <full videos.list item>}
        # This matches what perfume_trend_sdk/connectors/youtube/mappers.py produces.
        raw_items = []
        for shaped, vid_id in zip(search_shaped_items, video_ids):
            raw_items.append({
                "search_item": shaped,
                "video_details": stats_map.get(vid_id, {}),
            })

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
            # Transcript queue classification
            ts, tp = _classify_transcript_priority(raw_item, channel)
            n["transcript_status"] = ts
            n["transcript_priority"] = tp
            normalized_items.append(n)

        normalized_store.save_content_items(normalized_items)

        # Step 6: Resolve (title-only for channel_poll — see _resolver_input docstring)
        resolved_items = [
            resolver.resolve_content_item(_resolver_input(item))
            for item in normalized_items
        ]
        signal_store.save_resolved_signals(resolved_items)

        with session_scope() as db:
            batch_upsert_candidates(db, resolved_items, source_platform="youtube")

        entities_found = sum(len(r.get("resolved_entities", [])) for r in resolved_items)
        transcript_needed = sum(1 for n in normalized_items if n.get("transcript_status") == "needed")

        # consecutive_empty_polls resets to 0 when videos were found
        npa = _compute_next_poll_after(len(video_ids), 0, channel.get("quality_tier", "unrated"))

        print(
            f"    [ok] {len(video_ids)} videos → {entities_found} entity links"
            f"  transcript_needed={transcript_needed}"
            f"  next_poll_after={npa.isoformat()}"
        )

        _update_channel_after_poll(
            conn, channel_id,
            uploads_playlist_id=playlist_id,
            last_video_count=len(video_ids),
            consecutive_empty_polls=0,
            status="ok",
            next_poll_after=npa,
        )

        return {
            "channel_id": channel_id,
            "status": "ok",
            "video_count": len(video_ids),
            "transcript_needed": transcript_needed,
        }

    except Exception as exc:
        error_msg = str(exc)[:500]
        print(f"    [error] {error_msg}")
        new_empty_count = channel.get("consecutive_empty_polls", 0) + 1
        _update_channel_after_poll(
            conn, channel_id,
            consecutive_empty_polls=new_empty_count,
            status="error",
            error=error_msg,
            next_poll_after=_compute_next_poll_after(
                0, new_empty_count, channel.get("quality_tier", "unrated")
            ),
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
        "--force-all", action="store_true",
        help="Poll all active channels regardless of next_poll_after (bypass due-channel filter)"
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
    print(f"[ingest_youtube_channels] adaptive_polling={'disabled (--force-all)' if args.force_all else 'enabled'}")
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
        skip_not_due=not args.force_all,
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
    total_transcript_needed = sum(r.get("transcript_needed", 0) for r in results)

    print()
    print("=" * 60)
    print(f"[ingest_youtube_channels] Done.")
    print(f"  channels polled:     {len(results)}")
    print(f"  ok:                  {ok}")
    print(f"  empty:               {empty}")
    print(f"  errors:              {errors}")
    if dry:
        print(f"  dry_run:             {dry}")
    print(f"  total videos:        {total_videos}")
    print(f"  transcript_needed:   {total_transcript_needed}")
    print("=" * 60)


if __name__ == "__main__":
    main()
