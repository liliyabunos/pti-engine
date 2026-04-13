from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()

from perfume_trend_sdk.connectors.reddit_watchlist.config import RedditWatchlistConfig
from perfume_trend_sdk.connectors.reddit_watchlist.connector import RedditWatchlistConnector
from perfume_trend_sdk.normalizers.social_content.normalizer import SocialContentNormalizer
from perfume_trend_sdk.publishers.markdown.weekly_report import WeeklyMarkdownPublisher
from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import PerfumeResolver
from perfume_trend_sdk.storage.normalized.sqlite_store import NormalizedContentStore
from perfume_trend_sdk.storage.raw.filesystem import FilesystemRawStorage
from perfume_trend_sdk.storage.signals.sqlite_store import SignalStore
from perfume_trend_sdk.analysis.source_intelligence.analyzer import classify_source
from perfume_trend_sdk.analysis.source_intelligence.scoring import compute_influence

logger = logging.getLogger(__name__)


def iso_days_ago(days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_run_id(subreddit: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in subreddit.lower()).strip("_")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"reddit_{safe}_{ts}"


def _classify_reddit_source(item: dict) -> str:
    """Reddit posts are community signals, not influencer or brand content."""
    return "community"


def _compute_reddit_influence(item: dict) -> float:
    """Influence proxy for Reddit: score + comment depth, normalized.

    score × 0.7 + num_comments × 0.3, capped at a reasonable ceiling.
    Reddit influence is intentionally lower than influencer reach.
    """
    meta = item.get("media_metadata") or {}
    score = meta.get("score") or 0
    num_comments = meta.get("num_comments") or 0
    try:
        score = int(score)
        num_comments = int(num_comments)
    except (TypeError, ValueError):
        score = 0
        num_comments = 0
    return round((score * 0.7 + num_comments * 0.3), 2)


def run_pipeline(
    *,
    db_path: str,
    config_path: str,
    max_results: int = 25,
    lookback_days: int = 7,
    raw_dir: str = "data/raw",
    report_path: str = "outputs/reports/reddit_weekly_report.md",
) -> None:
    """Reddit ingestion pipeline:
    fetch → raw storage → normalize → source intelligence
    → normalized storage → resolve → signal storage → report.

    Raw storage happens BEFORE normalization (per architecture rules).
    Source intelligence is attached AFTER normalization.
    Pipeline continues without errors if Reddit connector returns no items.
    """
    config = RedditWatchlistConfig.from_yaml(config_path)

    if not config.enabled:
        print("[reddit] Connector disabled in config. Exiting.")
        return

    connector = RedditWatchlistConnector(config=config)
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

    active_subreddits = [s for s in config.subreddits if s.get("active", True)]

    if not active_subreddits:
        print("[reddit] No active subreddits in watchlist. Pipeline will produce empty report.")

    total_fetched = 0
    total_normalized = 0
    total_resolved = 0
    total_unresolved = 0

    for subreddit_cfg in active_subreddits:
        subreddit_name: str = subreddit_cfg.get("name", "")
        if not subreddit_name:
            logger.warning("[reddit] Subreddit entry missing name: %s", subreddit_cfg)
            continue

        print(f"[reddit] Fetching r/{subreddit_name}")
        logger.info(
            "[reddit] fetch_started subreddit=r/%s max_results=%d",
            subreddit_name,
            max_results,
        )

        run_id = build_run_id(subreddit_name)

        fetch_result = connector.fetch(
            subreddit_name,
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
            normalized = normalizer.normalize_reddit_item(raw_item, raw_payload_ref=raw_ref)
            normalized_items.append(normalized)

        # Source intelligence AFTER normalization — Reddit-specific logic
        for item in normalized_items:
            item["media_metadata"]["source_type"] = _classify_reddit_source(item)
            item["media_metadata"]["influence_score"] = _compute_reddit_influence(item)

        normalized_store.save_content_items(normalized_items)
        logger.info(
            "[reddit] normalized_count=%d subreddit=r/%s",
            len(normalized_items),
            subreddit_name,
        )

        resolved_items = [resolver.resolve_content_item(item) for item in normalized_items]
        signal_store.save_resolved_signals(resolved_items)

        # Count resolved vs unresolved
        resolved_count = sum(
            1 for r in resolved_items if r.get("resolved_entities")
        )
        unresolved_count = len(resolved_items) - resolved_count

        logger.info(
            "[reddit] resolved_count=%d unresolved_count=%d subreddit=r/%s",
            resolved_count,
            unresolved_count,
            subreddit_name,
        )

        if fetch_result.warnings:
            for warning in fetch_result.warnings:
                print(f"[reddit][warning] {warning}")

        total_fetched += fetch_result.fetched_count
        total_normalized += len(normalized_items)
        total_resolved += resolved_count
        total_unresolved += unresolved_count

    content_items = normalized_store.list_content_items()
    resolved_signals = signal_store.list_resolved_signals()

    publisher.publish(
        content_items=content_items,
        resolved_signals=resolved_signals,
        output_path=report_path,
    )

    print(f"\nTotal fetched:     {total_fetched}")
    print(f"Total normalized:  {total_normalized}")
    print(f"Total resolved:    {total_resolved}")
    print(f"Total unresolved:  {total_unresolved}")
    print(f"Report written to: {report_path}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingest Reddit subreddit posts into PTI pipeline."
    )
    parser.add_argument("--db", required=True, help="SQLite DB path")
    parser.add_argument(
        "--config",
        default="configs/watchlists/reddit_watchlist.yaml",
        help="Path to reddit_watchlist.yaml",
    )
    parser.add_argument("--max-results", type=int, default=25)
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--report-path", default="outputs/reports/reddit_weekly_report.md")
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
