from __future__ import annotations

"""
YouTube ingestion entry point for the market engine.

DB separation:
  --market-db   (or PTI_DB_PATH from .env)
                Receives canonical_content_items and resolved_signals.
                Must be the market engine DB (outputs/market_dev.db).
  --resolver-db (default: outputs/pti.db)
                Read-only source for PerfumeResolver (fragrance_master aliases).

Flow per query:
  YouTube API → raw items → normalize → NormalizedContentStore (market-db)
              → PerfumeResolver (resolver-db) → SignalStore (market-db)

After ingestion completes, run:
  python -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics --date <DATE>

Idempotency:
  NormalizedContentStore and SignalStore both use ON CONFLICT DO UPDATE,
  so re-running the same query for the same videos is safe.

Usage:
  python scripts/ingest_youtube.py
  python scripts/ingest_youtube.py --max-results 20 --lookback-days 7
  python scripts/ingest_youtube.py --queries-file configs/watchlists/perfume_queries.yaml
  python scripts/ingest_youtube.py --market-db outputs/market_dev.db --resolver-db outputs/pti.db
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Make sure the project root is on the path when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from perfume_trend_sdk.connectors.youtube.connector import YouTubeConnector
from perfume_trend_sdk.normalizers.social_content.normalizer import SocialContentNormalizer
from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import PerfumeResolver, make_resolver
from perfume_trend_sdk.storage.normalized.sqlite_store import NormalizedContentStore
from perfume_trend_sdk.storage.normalized.pg_store import PgNormalizedContentStore
from perfume_trend_sdk.storage.raw.filesystem import FilesystemRawStorage
from perfume_trend_sdk.storage.signals.sqlite_store import SignalStore
from perfume_trend_sdk.storage.signals.pg_store import PgSignalStore
from perfume_trend_sdk.analysis.source_intelligence.analyzer import classify_source
from perfume_trend_sdk.analysis.source_intelligence.scoring import compute_influence
from perfume_trend_sdk.storage.entities.candidate_store import batch_upsert_candidates
from perfume_trend_sdk.storage.postgres.db import session_scope


def _make_stores(market_db: str):
    """Return (normalized_store, signal_store) for the right backend.

    If DATABASE_URL is set in the environment, write to Railway Postgres.
    Otherwise fall back to local SQLite (market_db path).
    """
    database_url = os.environ.get("DATABASE_URL", "")
    if database_url:
        print(f"[ingest_youtube] backend     = postgres ({database_url.split('@')[-1]})")
        return PgNormalizedContentStore(database_url), PgSignalStore(database_url)
    print(f"[ingest_youtube] backend     = sqlite ({market_db})")
    ns = NormalizedContentStore(market_db)
    ss = SignalStore(market_db)
    ns.init_schema()
    ss.init_schema()
    return ns, ss


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_queries(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [q for q in data.get("queries", []) if q and not q.startswith("#")]


def _iso_days_ago(days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_id(query: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in query.lower()).strip("_")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"yt_{safe}_{ts}"


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run(
    *,
    market_db: str,
    resolver_db: str,
    queries_file: str,
    max_results: int,
    lookback_days: int,
    raw_dir: str,
) -> dict:
    """Run YouTube ingestion into the market engine DB.

    Returns a summary dict with counts.
    """
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "YOUTUBE_API_KEY is not set. "
            "Add it to .env or export it before running."
        )

    queries = _load_queries(queries_file)
    if not queries:
        raise RuntimeError(f"No queries found in {queries_file}")

    print(f"[ingest_youtube] market_db  = {market_db}")
    print(f"[ingest_youtube] resolver_db = {resolver_db}")
    print(f"[ingest_youtube] queries     = {len(queries)}")
    print(f"[ingest_youtube] max_results = {max_results} per query")
    print(f"[ingest_youtube] lookback    = {lookback_days} days")
    print()

    connector = YouTubeConnector(api_key=api_key)
    raw_storage = FilesystemRawStorage(base_dir=raw_dir)
    normalizer = SocialContentNormalizer()

    normalized_store, signal_store = _make_stores(market_db)

    # Resolver: Postgres (if DATABASE_URL set) else SQLite fallback
    resolver = make_resolver(resolver_db)
    resolver.store.init_schema()

    published_after = _iso_days_ago(lookback_days)

    total_fetched = 0
    total_normalized = 0
    total_resolved = 0
    total_entities_found = 0

    for query in queries:
        print(f"  [query] {query!r}")

        try:
            fetch_result = connector.fetch(
                query=query,
                max_results=max_results,
                published_after=published_after,
                region_code="US",
            )
        except Exception as exc:
            print(f"    [warn] fetch failed: {exc}")
            continue

        if fetch_result.fetched_count == 0:
            print(f"    [info] no results")
            continue

        run_id = _run_id(query)
        raw_refs = raw_storage.save_raw_batch(
            source_name="youtube",
            run_id=run_id,
            items=fetch_result.raw_items,
        )

        normalized_items = []
        for raw_item, raw_ref in zip(fetch_result.raw_items, raw_refs):
            normalized = normalizer.normalize_youtube_item(raw_item, raw_payload_ref=raw_ref)
            normalized_items.append(normalized)

        # Attach source intelligence metadata
        for item in normalized_items:
            item["media_metadata"]["source_type"] = classify_source(item)
            item["media_metadata"]["influence_score"] = compute_influence(item)

        normalized_store.save_content_items(normalized_items)

        # Resolve entities from normalized text
        resolved_items = [resolver.resolve_content_item(item) for item in normalized_items]
        signal_store.save_resolved_signals(resolved_items)

        # Save unresolved mentions to discovery candidates table
        with session_scope() as db:
            batch_upsert_candidates(db, resolved_items, source_platform="youtube")

        entities_found = sum(
            len(r.get("resolved_entities", [])) for r in resolved_items
        )

        print(
            f"    fetched={fetch_result.fetched_count}"
            f"  normalized={len(normalized_items)}"
            f"  entities={entities_found}"
        )

        total_fetched += fetch_result.fetched_count
        total_normalized += len(normalized_items)
        total_resolved += len(resolved_items)
        total_entities_found += entities_found

    summary = {
        "queries": len(queries),
        "total_fetched": total_fetched,
        "total_normalized": total_normalized,
        "total_resolved": total_resolved,
        "total_entities_found": total_entities_found,
        "market_db": market_db,
        "resolver_db": resolver_db,
    }

    print()
    print(f"[ingest_youtube] Done.")
    print(f"  queries run:       {summary['queries']}")
    print(f"  videos fetched:    {summary['total_fetched']}")
    print(f"  items normalized:  {summary['total_normalized']}")
    print(f"  items resolved:    {summary['total_resolved']}")
    print(f"  entities matched:  {summary['total_entities_found']}")
    print()
    print("Next step — run aggregation for today's date:")
    print(
        f"  python -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics"
        f" --date {datetime.now(timezone.utc).date().isoformat()}"
    )
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Ingest YouTube metadata into the PTI market engine.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--market-db",
        default=None,
        help=(
            "SQLite path for canonical_content_items and resolved_signals. "
            "Defaults to PTI_DB_PATH env var, then outputs/market_dev.db."
        ),
    )
    p.add_argument(
        "--resolver-db",
        default="data/resolver/pti.db",
        help="SQLite path for PerfumeResolver (fragrance_master / aliases).",
    )
    p.add_argument(
        "--queries-file",
        default="configs/watchlists/perfume_queries.yaml",
        help="YAML file containing the list of search queries.",
    )
    p.add_argument("--max-results", type=int, default=10,
                   help="Max videos per query (YouTube API max = 50).")
    p.add_argument("--lookback-days", type=int, default=30,
                   help="Only fetch videos published within this many days.")
    p.add_argument("--raw-dir", default="data/raw",
                   help="Directory for raw payload storage.")
    return p


def main() -> None:
    args = _build_parser().parse_args()

    # Resolve market DB: CLI arg > PTI_DB_PATH env > default
    market_db = (
        args.market_db
        or os.environ.get("PTI_DB_PATH")
        or "outputs/market_dev.db"
    )

    Path(args.raw_dir).mkdir(parents=True, exist_ok=True)

    run(
        market_db=market_db,
        resolver_db=args.resolver_db,
        queries_file=args.queries_file,
        max_results=args.max_results,
        lookback_days=args.lookback_days,
        raw_dir=args.raw_dir,
    )


if __name__ == "__main__":
    main()
