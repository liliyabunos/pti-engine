from __future__ import annotations

"""
Daily Market Aggregation Job — Market Engine v1

Reads from the existing NormalizedContentStore + SignalStore,
computes daily entity metrics, detects signal events, and writes
to market engine tables.

Runs on top of the existing pipeline — does NOT modify any
existing table.

Usage:
    python -m perfume_trend_sdk.workflows.run_daily_aggregation \
        --db outputs/pti.db \
        --date 2026-04-10
"""

import argparse
import logging
import os
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from perfume_trend_sdk.analysis.market_signals.aggregator import DailyAggregator
from perfume_trend_sdk.analysis.market_signals.detector import BreakoutDetector
from perfume_trend_sdk.storage.market.sqlite_store import MarketStore
from perfume_trend_sdk.storage.normalized.sqlite_store import NormalizedContentStore
from perfume_trend_sdk.storage.signals.sqlite_store import SignalStore

logger = logging.getLogger(__name__)


def run_aggregation(
    *,
    db_path: str,
    target_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the daily market aggregation and breakout detection.

    Args:
        db_path:     Path to the shared pipeline SQLite database.
        target_date: ISO date (YYYY-MM-DD) to aggregate. Defaults to today.

    Returns:
        Summary dict: {entities_processed, signals_detected, target_date}.
    """
    if target_date is None:
        target_date = date.today().isoformat()

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    logger.info(
        "daily_aggregation_started db=%s date=%s", db_path, target_date
    )

    # ── Init stores ──────────────────────────────────────────────────
    market_store = MarketStore(db_path)
    market_store.init_schema()

    normalized_store = NormalizedContentStore(db_path)
    normalized_store.init_schema()

    signal_store = SignalStore(db_path)
    signal_store.init_schema()

    # ── Load pipeline data ────────────────────────────────────────────
    content_items = normalized_store.list_content_items_full()
    resolved_signals = signal_store.list_resolved_signals()

    logger.info(
        "daily_aggregation_data_loaded content_items=%d resolved_signals=%d",
        len(content_items),
        len(resolved_signals),
    )

    # ── Aggregate ─────────────────────────────────────────────────────
    aggregator = DailyAggregator()

    # Load previous day snapshots for momentum / acceleration
    current_entities = market_store.list_entities()
    prev_snapshots: Dict[str, Dict[str, Any]] = {}
    for ent in current_entities:
        snap = market_store.get_prev_snapshot(ent["entity_id"], before_date=target_date)
        if snap:
            prev_snapshots[ent["entity_id"]] = snap

    snapshots = aggregator.aggregate_from_data(
        content_items=content_items,
        resolved_signals=resolved_signals,
        target_date=target_date,
        prev_snapshots=prev_snapshots,
    )

    # ── Upsert entity records ─────────────────────────────────────────
    entity_records = aggregator.build_entity_records(snapshots, created_at=now_iso)
    for rec in entity_records:
        market_store.upsert_entity(**rec)

    # ── Upsert snapshots ──────────────────────────────────────────────
    for snap in snapshots:
        market_store.upsert_daily_snapshot(snap)

    logger.info(
        "daily_aggregation_snapshots_written count=%d", len(snapshots)
    )

    # ── Detect signals ─────────────────────────────────────────────────
    detector = BreakoutDetector()
    all_signals = detector.detect_batch(
        snapshots=snapshots,
        prev_snapshots=prev_snapshots,
        detected_at=target_date,
    )

    if all_signals:
        market_store.save_signals(all_signals)

    logger.info(
        "daily_aggregation_signals_detected count=%d", len(all_signals)
    )
    logger.info(
        "daily_aggregation_completed date=%s entities=%d signals=%d",
        target_date,
        len(snapshots),
        len(all_signals),
    )

    print(f"Date:              {target_date}")
    print(f"Entities processed: {len(snapshots)}")
    print(f"Signals detected:  {len(all_signals)}")
    if all_signals:
        for s in all_signals:
            print(f"  [{s['signal_type']}] {s['entity_id']} strength={s.get('strength', s.get('score', 0.0))}")

    return {
        "target_date": target_date,
        "entities_processed": len(snapshots),
        "signals_detected": len(all_signals),
        "signal_types": [s["signal_type"] for s in all_signals],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run daily market aggregation for PTI SDK market engine."
    )
    parser.add_argument("--db", required=True, help="SQLite DB path")
    parser.add_argument(
        "--date",
        default=None,
        help="ISO date to aggregate (YYYY-MM-DD). Defaults to today.",
    )
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = build_arg_parser()
    args = parser.parse_args()
    os.makedirs(os.path.dirname(args.db) if os.path.dirname(args.db) else ".", exist_ok=True)
    run_aggregation(db_path=args.db, target_date=args.date)


if __name__ == "__main__":
    main()
