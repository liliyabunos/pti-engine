from __future__ import annotations

"""
Reddit public JSON ingestion entry point for the market engine.

Uses Reddit public JSON endpoints — no OAuth, no API credentials required.
Mirrors ingest_youtube.py structure exactly.

DB separation (same as YouTube):
  --market-db   (or PTI_DB_PATH from .env)
                Receives canonical_content_items and resolved_signals.
  --resolver-db (default: outputs/pti.db)
                Read-only source for PerfumeResolver.

Flow per subreddit:
  Reddit public JSON → raw items → normalize → NormalizedContentStore
                     → PerfumeResolver → SignalStore

After ingestion, run:
  python -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics --date <DATE>

Idempotency:
  Both NormalizedContentStore and SignalStore use ON CONFLICT DO UPDATE,
  so re-running the same subreddits for the same day is safe.

Usage — minimal first run (STEP 1 recommended):
  python scripts/ingest_reddit.py --subreddit fragrance --limit 10

Usage — all active subreddits, lookback window:
  python scripts/ingest_reddit.py --lookback-days 3 --limit 25

Usage — specific subreddit list from config:
  python scripts/ingest_reddit.py --watchlist configs/watchlists/reddit_watchlist.yaml --limit 25

No env vars required for v1 (public JSON, no credentials).
PTI_DB_PATH must be set in .env or --market-db must be passed.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from perfume_trend_sdk.connectors.reddit_watchlist.client import RedditAPIError
from perfume_trend_sdk.connectors.reddit_watchlist.config import RedditWatchlistConfig
from perfume_trend_sdk.connectors.reddit_watchlist.connector import RedditWatchlistConnector
from perfume_trend_sdk.normalizers.social_content.normalizer import SocialContentNormalizer
from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import PerfumeResolver
from perfume_trend_sdk.storage.normalized.sqlite_store import NormalizedContentStore
from perfume_trend_sdk.storage.normalized.pg_store import PgNormalizedContentStore
from perfume_trend_sdk.storage.raw.filesystem import FilesystemRawStorage
from perfume_trend_sdk.storage.signals.sqlite_store import SignalStore
from perfume_trend_sdk.storage.signals.pg_store import PgSignalStore
from perfume_trend_sdk.workflows.ingest_reddit_to_signals import (
    _classify_reddit_source,
    _compute_reddit_influence,
)
from perfume_trend_sdk.storage.entities.candidate_store import batch_upsert_candidates
from perfume_trend_sdk.storage.postgres.db import session_scope


def _make_stores(market_db: str):
    """Return (normalized_store, signal_store) for the right backend."""
    database_url = os.environ.get("DATABASE_URL", "")
    if database_url:
        print(f"[ingest_reddit] backend     = postgres ({database_url.split('@')[-1]})")
        return PgNormalizedContentStore(database_url), PgSignalStore(database_url)
    print(f"[ingest_reddit] backend     = sqlite ({market_db})")
    ns = NormalizedContentStore(market_db)
    ss = SignalStore(market_db)
    ns.init_schema()
    ss.init_schema()
    return ns, ss


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso_days_ago(days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_id(subreddit: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in subreddit.lower()).strip("_")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"reddit_{safe}_{ts}"


def _resolve_db(arg: str | None) -> str:
    if arg:
        return arg
    env = os.environ.get("PTI_DB_PATH")
    if env:
        return env
    return "outputs/market_dev.db"


def _load_subreddits(watchlist_file: str) -> list[str]:
    """Return active subreddit names from watchlist YAML."""
    try:
        with open(watchlist_file, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        print(f"[ingest_reddit] ERROR: watchlist file not found: {watchlist_file}")
        sys.exit(1)
    entries = data.get("subreddits") or []
    return [e["name"] for e in entries if e.get("active", True) and e.get("name")]


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run(
    *,
    market_db: str,
    resolver_db: str,
    subreddits: list[str],
    limit: int,
    lookback_days: int | None,
    sort_mode: str,
    raw_dir: str,
) -> dict:
    """
    Run Reddit public JSON ingestion into the market engine DB.

    Returns a summary dict.
    """
    published_after: str | None = _iso_days_ago(lookback_days) if lookback_days else None

    print(f"[ingest_reddit] market_db   = {market_db}")
    print(f"[ingest_reddit] resolver_db = {resolver_db}")
    print(f"[ingest_reddit] subreddits  = {subreddits}")
    print(f"[ingest_reddit] sort_mode   = {sort_mode}")
    print(f"[ingest_reddit] limit       = {limit} per subreddit")
    print(f"[ingest_reddit] lookback    = {lookback_days} days" if lookback_days else
          "[ingest_reddit] lookback    = none (all recent)")
    print()

    # Build a minimal config pointing at a synthetic watchlist list
    # The connector only needs enabled + sort_mode — subreddits are passed per-call
    config = RedditWatchlistConfig(
        enabled=True,
        sort_mode=sort_mode,
        fetch_limit=limit,
    )
    connector = RedditWatchlistConnector(config=config)

    raw_storage = FilesystemRawStorage(base_dir=raw_dir)
    normalizer = SocialContentNormalizer()

    normalized_store, signal_store = _make_stores(market_db)

    resolver = PerfumeResolver(resolver_db)
    resolver.store.init_schema()

    total_fetched = 0
    total_normalized = 0
    total_resolved = 0
    total_entities_found = 0

    for subreddit in subreddits:
        print(f"  [r/{subreddit}]")

        try:
            fetch_result = connector.fetch(
                subreddit,
                max_results=limit,
                published_after=published_after,
            )
        except Exception as exc:
            print(f"    [warn] fetch error: {exc}")
            continue

        if fetch_result.warnings:
            for w in fetch_result.warnings:
                print(f"    [warn] {w}")

        if not fetch_result.raw_items:
            print(f"    [info] 0 posts returned")
            continue

        run_id = _run_id(subreddit)
        raw_refs = raw_storage.save_raw_batch(
            source_name=fetch_result.source_name,
            run_id=run_id,
            items=fetch_result.raw_items,
        )

        normalized_items = []
        for raw_item, raw_ref in zip(fetch_result.raw_items, raw_refs):
            normalized = normalizer.normalize_reddit_item(raw_item, raw_payload_ref=raw_ref)
            normalized_items.append(normalized)

        # Source intelligence metadata
        for item in normalized_items:
            item["media_metadata"]["source_type"] = _classify_reddit_source(item)
            item["media_metadata"]["influence_score"] = _compute_reddit_influence(item)

        normalized_store.save_content_items(normalized_items)

        resolved_items = [resolver.resolve_content_item(item) for item in normalized_items]
        signal_store.save_resolved_signals(resolved_items)

        # Save unresolved mentions to discovery candidates table
        with session_scope() as db:
            batch_upsert_candidates(db, resolved_items, source_platform="reddit")

        entities_found = sum(
            len(r.get("resolved_entities", [])) for r in resolved_items
        )

        print(
            f"    fetched={fetch_result.fetched_count}"
            f"  normalized={len(normalized_items)}"
            f"  entities={entities_found}"
            + (f"  next_cursor={fetch_result.next_cursor}" if fetch_result.next_cursor else "")
        )

        total_fetched += fetch_result.fetched_count
        total_normalized += len(normalized_items)
        total_resolved += len(resolved_items)
        total_entities_found += entities_found

    summary = {
        "subreddits": len(subreddits),
        "total_fetched": total_fetched,
        "total_normalized": total_normalized,
        "total_resolved": total_resolved,
        "total_entities_found": total_entities_found,
        "market_db": market_db,
        "resolver_db": resolver_db,
    }

    print()
    print("[ingest_reddit] Done.")
    print(f"  subreddits:        {summary['subreddits']}")
    print(f"  posts fetched:     {summary['total_fetched']}")
    print(f"  items normalized:  {summary['total_normalized']}")
    print(f"  items resolved:    {summary['total_resolved']}")
    print(f"  entities matched:  {summary['total_entities_found']}")
    print()
    today = datetime.now(timezone.utc).date().isoformat()
    print("Next step — run aggregation:")
    print(
        f"  python -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics"
        f" --date {today}"
    )
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Ingest Reddit public JSON posts into the PTI market engine.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--market-db",
        default=None,
        help="SQLite path for market DB. Defaults to PTI_DB_PATH env var.",
    )
    p.add_argument(
        "--resolver-db",
        default="data/resolver/pti.db",
        help="SQLite path for PerfumeResolver (fragrance_master / aliases).",
    )

    # Source selection: single subreddit OR watchlist file
    src_group = p.add_mutually_exclusive_group()
    src_group.add_argument(
        "--subreddit",
        default=None,
        help='Single subreddit name for minimal test, e.g. "fragrance".',
    )
    src_group.add_argument(
        "--watchlist",
        default="configs/watchlists/reddit_watchlist.yaml",
        help="YAML watchlist file with subreddit list.",
    )

    p.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Max posts per subreddit per run (API max=100).",
    )
    p.add_argument(
        "--lookback-days",
        type=int,
        default=3,
        help="Only ingest posts from the last N days. 0 = no filter.",
    )
    p.add_argument(
        "--sort-mode",
        choices=["new", "hot"],
        default="new",
        help='Subreddit listing sort: "new" for recency, "hot" for engagement.',
    )
    p.add_argument(
        "--raw-dir",
        default="data/raw",
        help="Directory for raw payload storage.",
    )
    return p


def main() -> None:
    p = _build_parser()
    args = p.parse_args()

    market_db = _resolve_db(args.market_db)

    if args.subreddit:
        subreddits = [args.subreddit]
    else:
        subreddits = _load_subreddits(args.watchlist)
        if not subreddits:
            print(f"[ingest_reddit] No active subreddits in {args.watchlist}")
            sys.exit(1)

    lookback = args.lookback_days if args.lookback_days > 0 else None

    run(
        market_db=market_db,
        resolver_db=args.resolver_db,
        subreddits=subreddits,
        limit=args.limit,
        lookback_days=lookback,
        sort_mode=args.sort_mode,
        raw_dir=args.raw_dir,
    )


if __name__ == "__main__":
    main()
