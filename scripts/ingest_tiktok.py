from __future__ import annotations

"""
TikTok keyword ingestion entry point for the market engine.

Uses TikTok Research API v2 — keyword-based video search.
Mirrors ingest_youtube.py structure exactly.

DB separation (same as YouTube):
  --market-db   (or PTI_DB_PATH from .env)
                Receives canonical_content_items and resolved_signals.
  --resolver-db (default: outputs/pti.db)
                Read-only source for PerfumeResolver.

Flow per query:
  TikTok Research API → raw items → normalize → NormalizedContentStore
                      → PerfumeResolver → SignalStore

Date handling:
  TikTok Research API expects YYYYMMDD.
  --start-date and --end-date accept either YYYY-MM-DD or YYYYMMDD.
  --lookback-days is a convenience shorthand (overrides explicit dates).

After ingestion, run:
  python -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics --date <DATE>

Idempotency:
  Both NormalizedContentStore and SignalStore use ON CONFLICT DO UPDATE,
  so re-running the same queries for the same date range is safe.

Usage — minimal test (STEP 1):
  python scripts/ingest_tiktok.py --query "Dior Sauvage" --date 20260410

Usage — single date, all queries:
  python scripts/ingest_tiktok.py --date 20260410

Usage — date range, all queries:
  python scripts/ingest_tiktok.py --start-date 20260408 --end-date 20260410

Usage — lookback window (default):
  python scripts/ingest_tiktok.py --lookback-days 3 --max-count 20

Env vars required:
  TIKTOK_CLIENT_KEY     — Research API app client key
  TIKTOK_CLIENT_SECRET  — Research API app client secret
  PTI_DB_PATH           — market DB path (or pass --market-db)
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

from perfume_trend_sdk.analysis.source_intelligence.analyzer import classify_source
from perfume_trend_sdk.analysis.source_intelligence.scoring import compute_influence
from perfume_trend_sdk.connectors.tiktok_watchlist.client import (
    TikTokAPIError,
    TikTokWatchlistClient,
)
from perfume_trend_sdk.normalizers.social_content.normalizer import SocialContentNormalizer
from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import PerfumeResolver
from perfume_trend_sdk.storage.normalized.sqlite_store import NormalizedContentStore
from perfume_trend_sdk.storage.raw.filesystem import FilesystemRawStorage
from perfume_trend_sdk.storage.signals.sqlite_store import SignalStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_queries(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [q for q in data.get("queries", []) if q and not str(q).startswith("#")]


def _yyyymmdd(value: str) -> str:
    """Normalise YYYY-MM-DD or YYYYMMDD → YYYYMMDD (TikTok API format)."""
    return value.replace("-", "")


def _lookback_dates(days: int) -> tuple[str, str]:
    """Return (start_date, end_date) in YYYYMMDD for the last N calendar days."""
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days)
    return start.strftime("%Y%m%d"), today.strftime("%Y%m%d")


def _run_id(query: str, start: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in query.lower()).strip("_")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"tiktok_{safe}_{start}_{ts}"


def _resolve_db(arg: str | None) -> str:
    if arg:
        return arg
    env = os.environ.get("PTI_DB_PATH")
    if env:
        return env
    return "outputs/market_dev.db"


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run(
    *,
    market_db: str,
    resolver_db: str,
    queries: list[str],
    start_date: str,
    end_date: str,
    max_count: int,
    raw_dir: str,
) -> dict:
    """
    Run TikTok keyword ingestion into the market engine DB.

    Returns a summary dict with counts.
    """
    client_key = os.environ.get("TIKTOK_CLIENT_KEY", "")
    client_secret = os.environ.get("TIKTOK_CLIENT_SECRET", "")
    if not client_key or not client_secret:
        raise RuntimeError(
            "TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET are not set.\n"
            "Add them to .env:\n"
            "  TIKTOK_CLIENT_KEY=<your key>\n"
            "  TIKTOK_CLIENT_SECRET=<your secret>\n"
            "Apply at https://developers.tiktok.com/products/research-api/"
        )

    print(f"[ingest_tiktok] market_db   = {market_db}")
    print(f"[ingest_tiktok] resolver_db = {resolver_db}")
    print(f"[ingest_tiktok] queries     = {len(queries)}")
    print(f"[ingest_tiktok] date_range  = {start_date} → {end_date}")
    print(f"[ingest_tiktok] max_count   = {max_count} per query")
    print()

    tiktok = TikTokWatchlistClient(
        client_key=client_key,
        client_secret=client_secret,
    )

    raw_storage = FilesystemRawStorage(base_dir=raw_dir)
    normalizer = SocialContentNormalizer()

    normalized_store = NormalizedContentStore(market_db)
    signal_store = SignalStore(market_db)
    normalized_store.init_schema()
    signal_store.init_schema()

    resolver = PerfumeResolver(resolver_db)
    resolver.store.init_schema()

    total_fetched = 0
    total_normalized = 0
    total_resolved = 0
    total_entities_found = 0

    for query in queries:
        print(f"  [query] {query!r}")

        try:
            videos, next_cursor = tiktok.search_videos(
                query=query,
                start_date=start_date,
                end_date=end_date,
                max_count=max_count,
                cursor=0,
            )
        except TikTokAPIError as exc:
            print(f"    [warn] TikTok API error: {exc}")
            continue
        except Exception as exc:
            print(f"    [warn] unexpected error: {exc}")
            continue

        if not videos:
            print(f"    [info] 0 results")
            continue

        run_id = _run_id(query, start_date)
        raw_refs = raw_storage.save_raw_batch(
            source_name="tiktok",
            run_id=run_id,
            items=videos,
        )

        normalized_items = []
        for raw_item, raw_ref in zip(videos, raw_refs):
            normalized = normalizer.normalize_tiktok_item(raw_item, raw_payload_ref=raw_ref)
            normalized_items.append(normalized)

        # Source intelligence metadata
        for item in normalized_items:
            item["media_metadata"]["source_type"] = classify_source(item)
            item["media_metadata"]["influence_score"] = compute_influence(item)

        normalized_store.save_content_items(normalized_items)

        resolved_items = [resolver.resolve_content_item(item) for item in normalized_items]
        signal_store.save_resolved_signals(resolved_items)

        entities_found = sum(
            len(r.get("resolved_entities", [])) for r in resolved_items
        )

        print(
            f"    fetched={len(videos)}"
            f"  normalized={len(normalized_items)}"
            f"  entities={entities_found}"
            + (f"  next_cursor={next_cursor}" if next_cursor else "")
        )

        total_fetched += len(videos)
        total_normalized += len(normalized_items)
        total_resolved += len(resolved_items)
        total_entities_found += entities_found

    summary = {
        "queries": len(queries),
        "total_fetched": total_fetched,
        "total_normalized": total_normalized,
        "total_resolved": total_resolved,
        "total_entities_found": total_entities_found,
        "start_date": start_date,
        "end_date": end_date,
        "market_db": market_db,
        "resolver_db": resolver_db,
    }

    print()
    print("[ingest_tiktok] Done.")
    print(f"  queries run:       {summary['queries']}")
    print(f"  videos fetched:    {summary['total_fetched']}")
    print(f"  items normalized:  {summary['total_normalized']}")
    print(f"  items resolved:    {summary['total_resolved']}")
    print(f"  entities matched:  {summary['total_entities_found']}")
    print()
    # TikTok uses YYYYMMDD; aggregation job uses YYYY-MM-DD
    agg_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
    print("Next step — run aggregation:")
    print(
        f"  python -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics"
        f" --date {agg_date}"
    )
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Ingest TikTok keyword search results into the PTI market engine.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--market-db",
        default=None,
        help="SQLite path for market DB. Defaults to PTI_DB_PATH env var.",
    )
    p.add_argument(
        "--resolver-db",
        default="outputs/pti.db",
        help="SQLite path for PerfumeResolver (fragrance_master / aliases).",
    )

    # Query source: single keyword OR YAML file
    query_group = p.add_mutually_exclusive_group()
    query_group.add_argument(
        "--query",
        default=None,
        help='Single keyword for STEP 1 minimal test, e.g. "Dior Sauvage".',
    )
    query_group.add_argument(
        "--queries-file",
        default="configs/watchlists/tiktok_queries.yaml",
        help="YAML file with list of search queries.",
    )

    # Date source: single date shorthand OR explicit range OR lookback window
    date_group = p.add_mutually_exclusive_group()
    date_group.add_argument(
        "--date",
        default=None,
        help="Single date (YYYYMMDD or YYYY-MM-DD). Sets start=end=date.",
    )
    date_group.add_argument(
        "--lookback-days",
        type=int,
        default=None,
        help="Convenience: use last N calendar days as date range.",
    )

    p.add_argument("--start-date", default=None, help="Start date YYYYMMDD (used when --date not set).")
    p.add_argument("--end-date", default=None, help="End date YYYYMMDD (used when --date not set).")
    p.add_argument("--max-count", type=int, default=10, help="Max videos per query (API max=100).")
    p.add_argument("--raw-dir", default="data/raw", help="Directory for raw payload storage.")
    return p


def main() -> None:
    p = _build_parser()
    args = p.parse_args()

    market_db = _resolve_db(args.market_db)

    # Resolve date range
    if args.date:
        start_date = end_date = _yyyymmdd(args.date)
    elif args.lookback_days:
        start_date, end_date = _lookback_dates(args.lookback_days)
    elif args.start_date and args.end_date:
        start_date = _yyyymmdd(args.start_date)
        end_date = _yyyymmdd(args.end_date)
    else:
        # Default: today only
        today = datetime.now(timezone.utc).date().strftime("%Y%m%d")
        start_date = end_date = today

    # Resolve query list
    if args.query:
        queries = [args.query]
    else:
        queries_file = args.queries_file
        if not Path(queries_file).exists():
            print(f"[ingest_tiktok] ERROR: queries file not found: {queries_file}")
            sys.exit(1)
        queries = _load_queries(queries_file)
        if not queries:
            print(f"[ingest_tiktok] ERROR: no queries found in {queries_file}")
            sys.exit(1)

    try:
        run(
            market_db=market_db,
            resolver_db=args.resolver_db,
            queries=queries,
            start_date=start_date,
            end_date=end_date,
            max_count=args.max_count,
            raw_dir=args.raw_dir,
        )
    except RuntimeError as exc:
        print(f"\n[ingest_tiktok] FATAL: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
