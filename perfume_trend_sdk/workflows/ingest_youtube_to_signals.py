from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone
from typing import List

import yaml
from dotenv import load_dotenv

load_dotenv()

from perfume_trend_sdk.connectors.youtube.connector import YouTubeConnector
from perfume_trend_sdk.normalizers.social_content.normalizer import SocialContentNormalizer
from perfume_trend_sdk.publishers.markdown.weekly_report import WeeklyMarkdownPublisher
from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import PerfumeResolver
from perfume_trend_sdk.storage.normalized.sqlite_store import NormalizedContentStore
from perfume_trend_sdk.storage.raw.filesystem import FilesystemRawStorage
from perfume_trend_sdk.storage.signals.sqlite_store import SignalStore
from perfume_trend_sdk.analysis.source_intelligence.analyzer import classify_source
from perfume_trend_sdk.analysis.source_intelligence.scoring import compute_influence


def load_queries(queries_file: str) -> List[str]:
    with open(queries_file, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("queries", [])


def iso_days_ago(days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_run_id(query: str) -> str:
    safe_query = "".join(ch if ch.isalnum() else "_" for ch in query.lower()).strip("_")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{safe_query}_{ts}"


def run_pipeline(
    *,
    db_path: str,
    queries_file: str,
    max_results: int,
    lookback_days: int,
    raw_dir: str,
    report_path: str,
) -> None:
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        raise RuntimeError("YOUTUBE_API_KEY is not set")

    queries = load_queries(queries_file)
    if not queries:
        raise RuntimeError(f"No queries found in {queries_file}")

    connector = YouTubeConnector(api_key=api_key)
    raw_storage = FilesystemRawStorage(base_dir=raw_dir)
    normalizer = SocialContentNormalizer()
    normalized_store = NormalizedContentStore(db_path)
    signal_store = SignalStore(db_path)
    resolver = PerfumeResolver(db_path)
    publisher = WeeklyMarkdownPublisher()

    normalized_store.init_schema()
    signal_store.init_schema()
    resolver.store.init_schema()

    published_after = iso_days_ago(lookback_days)

    total_fetched = 0
    total_normalized = 0
    total_resolved = 0

    for query in queries:
        print(f"[query] {query}")
        run_id = build_run_id(query)

        fetch_result = connector.fetch(
            query=query,
            max_results=max_results,
            published_after=published_after,
            region_code="US",
        )

        raw_refs = raw_storage.save_raw_batch(
            source_name=fetch_result.source_name,
            run_id=run_id,
            items=fetch_result.raw_items,
        )

        normalized_items = []
        for raw_item, raw_ref in zip(fetch_result.raw_items, raw_refs):
            normalized = normalizer.normalize_youtube_item(raw_item, raw_payload_ref=raw_ref)
            normalized_items.append(normalized)

        for item in normalized_items:
            item["media_metadata"]["source_type"] = classify_source(item)
            item["media_metadata"]["influence_score"] = compute_influence(item)

        normalized_store.save_content_items(normalized_items)

        resolved_items = [resolver.resolve_content_item(item) for item in normalized_items]
        signal_store.save_resolved_signals(resolved_items)

        total_fetched += fetch_result.fetched_count
        total_normalized += len(normalized_items)
        total_resolved += len(resolved_items)

    content_items = normalized_store.list_content_items()
    resolved_signals = signal_store.list_resolved_signals()

    publisher.publish(
        content_items=content_items,
        resolved_signals=resolved_signals,
        output_path=report_path,
    )

    print(f"\nTotal fetched:    {total_fetched}")
    print(f"Total normalized: {total_normalized}")
    print(f"Total resolved:   {total_resolved}")
    print(f"Report written to: {report_path}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest YouTube search results into PTI pipeline.")
    parser.add_argument("--db", required=True, help="SQLite DB path")
    parser.add_argument(
        "--queries-file",
        default="configs/watchlists/perfume_queries.yaml",
        help="YAML file with list of search queries",
    )
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--report-path", default="outputs/reports/weekly_report.md")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.report_path), exist_ok=True)

    run_pipeline(
        db_path=args.db,
        queries_file=args.queries_file,
        max_results=args.max_results,
        lookback_days=args.lookback_days,
        raw_dir=args.raw_dir,
        report_path=args.report_path,
    )


if __name__ == "__main__":
    main()
