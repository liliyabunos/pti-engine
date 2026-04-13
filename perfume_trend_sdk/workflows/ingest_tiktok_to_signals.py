from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()

from perfume_trend_sdk.connectors.tiktok_watchlist.config import TikTokWatchlistConfig
from perfume_trend_sdk.connectors.tiktok_watchlist.connector import TikTokWatchlistConnector
from perfume_trend_sdk.normalizers.social_content.normalizer import SocialContentNormalizer
from perfume_trend_sdk.publishers.markdown.weekly_report import WeeklyMarkdownPublisher
from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import PerfumeResolver
from perfume_trend_sdk.storage.normalized.sqlite_store import NormalizedContentStore
from perfume_trend_sdk.storage.raw.filesystem import FilesystemRawStorage
from perfume_trend_sdk.storage.signals.sqlite_store import SignalStore
from perfume_trend_sdk.analysis.source_intelligence.analyzer import classify_source
from perfume_trend_sdk.analysis.source_intelligence.scoring import compute_influence


def iso_days_ago(days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_run_id(handle: str) -> str:
    safe_handle = "".join(ch if ch.isalnum() else "_" for ch in handle.lower()).strip("_")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"tiktok_{safe_handle}_{ts}"


def run_pipeline(
    *,
    db_path: str,
    config_path: str,
    max_results: int = 25,
    lookback_days: int = 30,
    raw_dir: str = "data/raw",
    report_path: str = "outputs/reports/tiktok_weekly_report.md",
) -> None:
    """
    TikTok ingestion pipeline: fetch -> raw storage -> normalize -> source intelligence
    -> normalized storage -> resolve -> signal storage -> report.

    Raw storage happens BEFORE normalization (per architecture rules).
    Source intelligence hooks are applied AFTER normalization.
    Pipeline continues without errors if TikTok connector returns no items.
    """
    config = TikTokWatchlistConfig.from_yaml(config_path)

    if not config.enabled:
        print(f"[tiktok] Connector disabled in config. Exiting.")
        return

    connector = TikTokWatchlistConnector(config=config)

    raw_storage = FilesystemRawStorage(base_dir=raw_dir)
    normalizer = SocialContentNormalizer()
    normalized_store = NormalizedContentStore(db_path)
    signal_store = SignalStore(db_path)
    resolver = PerfumeResolver(db_path)
    publisher = WeeklyMarkdownPublisher()

    normalized_store.init_schema()
    signal_store.init_schema()
    resolver.store.init_schema()

    published_after: Optional[str] = iso_days_ago(lookback_days)

    total_fetched = 0
    total_normalized = 0
    total_resolved = 0

    active_accounts = [a for a in config.accounts if a.get("active", True)]

    if not active_accounts:
        print("[tiktok] No active accounts in watchlist. Pipeline will produce empty report.")

    for account in active_accounts:
        handle: str = account.get("account_handle", "")
        if not handle:
            print(f"[tiktok] Skipping account entry with no handle: {account}")
            continue

        print(f"[tiktok] Fetching @{handle}")
        run_id = build_run_id(handle)

        fetch_result = connector.fetch(
            max_results=max_results,
            published_after=published_after,
        )

        # Raw storage BEFORE normalization (architecture rule)
        raw_refs: List[str] = raw_storage.save_raw_batch(
            source_name=fetch_result.source_name,
            run_id=run_id,
            items=fetch_result.raw_items,
        )

        normalized_items = []
        for raw_item, raw_ref in zip(fetch_result.raw_items, raw_refs):
            normalized = normalizer.normalize_tiktok_item(raw_item, raw_payload_ref=raw_ref)
            normalized_items.append(normalized)

        # Source intelligence hooks AFTER normalization (architecture rule)
        for item in normalized_items:
            item["media_metadata"]["source_type"] = classify_source(item)
            item["media_metadata"]["influence_score"] = compute_influence(item)

        normalized_store.save_content_items(normalized_items)

        resolved_items = [resolver.resolve_content_item(item) for item in normalized_items]
        signal_store.save_resolved_signals(resolved_items)

        if fetch_result.warnings:
            for warning in fetch_result.warnings:
                print(f"[tiktok][warning] {warning}")

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
    parser = argparse.ArgumentParser(
        description="Ingest TikTok watchlist posts into PTI pipeline."
    )
    parser.add_argument("--db", required=True, help="SQLite DB path")
    parser.add_argument(
        "--config",
        default="configs/watchlists/tiktok_watchlist.yaml",
        help="Path to tiktok_watchlist.yaml",
    )
    parser.add_argument("--max-results", type=int, default=25)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--report-path", default="outputs/reports/tiktok_weekly_report.md")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.report_path), exist_ok=True)

    run_pipeline(
        db_path=args.db,
        config_path=args.config,
        max_results=args.max_results,
        lookback_days=args.lookback_days,
        raw_dir=args.raw_dir,
        report_path=args.report_path,
    )


if __name__ == "__main__":
    main()
