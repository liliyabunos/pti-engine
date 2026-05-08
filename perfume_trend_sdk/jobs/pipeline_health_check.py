from __future__ import annotations

"""
P3 — Pipeline Health Check

Runs at the end of each pipeline cycle (morning + evening) to detect silent
ingestion / resolver collapse, especially Reddit outages.

Usage:
    python3 -m perfume_trend_sdk.jobs.pipeline_health_check --date 2026-05-07 --run-label evening
    python3 -m perfume_trend_sdk.jobs.pipeline_health_check --date 2026-05-07 --run-label morning

Exit code is always 0 — health failures are logged only; they do not stop the pipeline.

Log markers (easy to grep / Railway alert on):
    PIPELINE_HEALTH_OK
    PIPELINE_HEALTH_WARNING
    PIPELINE_HEALTH_CRITICAL
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from typing import List, Tuple

from sqlalchemy import text

from perfume_trend_sdk.db.market.session import _make_engine, get_database_url

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(message)s",
    stream=sys.stdout,
)
_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# entity_mentions written today
_ENTITY_MENTIONS_CRITICAL = 50
_ENTITY_MENTIONS_WARNING = 100

# canonical_content_items ingested today
_CONTENT_ITEMS_TOTAL_CRITICAL = 100   # evening only
_CONTENT_ITEMS_YOUTUBE_WARNING = 50

# public_safe_signals today
_SIGNALS_WARNING = 20  # evening only


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

def _fetch_metrics(engine, date: str) -> dict:
    """Run all health-check SQL queries against the production DB."""
    with engine.connect() as conn:

        # 1. Total entity_mentions today (occurred_at is timestamptz)
        total_mentions = conn.execute(
            text("""
                SELECT COUNT(*)
                FROM entity_mentions
                WHERE DATE(occurred_at) = :d
            """),
            {"d": date},
        ).scalar() or 0

        # 2. Reddit entity_mentions today — source_platform is on entity_mentions directly
        reddit_mentions = conn.execute(
            text("""
                SELECT COUNT(*)
                FROM entity_mentions
                WHERE DATE(occurred_at) = :d
                  AND source_platform = 'reddit'
            """),
            {"d": date},
        ).scalar() or 0

        # 3. canonical_content_items by platform today (collected_at is timestamptz)
        platform_rows = conn.execute(
            text("""
                SELECT source_platform, COUNT(*) AS cnt
                FROM canonical_content_items
                WHERE DATE(collected_at::timestamptz) = :d
                GROUP BY source_platform
            """),
            {"d": date},
        ).fetchall()
        platform_counts = {r[0]: r[1] for r in platform_rows}

        # 4. signals today (detected_at is timestamptz)
        signals_today = conn.execute(
            text("""
                SELECT COUNT(*)
                FROM signals
                WHERE DATE(detected_at) = :d
            """),
            {"d": date},
        ).scalar() or 0

    return {
        "total_mentions": total_mentions,
        "reddit_mentions": reddit_mentions,
        "platform_counts": platform_counts,
        "signals_today": signals_today,
        "youtube_items": platform_counts.get("youtube", 0),
        "reddit_items": platform_counts.get("reddit", 0),
        "total_items": sum(platform_counts.values()),
    }


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _evaluate(metrics: dict, run_label: str) -> Tuple[str, List[str]]:
    """
    Returns (overall_level, [message, ...]) where level is 'OK'|'WARNING'|'CRITICAL'.
    """
    issues: List[str] = []
    level = "OK"

    def _warn(msg: str) -> None:
        nonlocal level
        issues.append(f"WARNING {msg}")
        if level == "OK":
            level = "WARNING"

    def _crit(msg: str) -> None:
        nonlocal level
        issues.append(f"CRITICAL {msg}")
        level = "CRITICAL"

    total_mentions = metrics["total_mentions"]
    reddit_mentions = metrics["reddit_mentions"]
    reddit_items = metrics["reddit_items"]
    youtube_items = metrics["youtube_items"]
    total_items = metrics["total_items"]
    signals_today = metrics["signals_today"]

    # --- Check 1: Total entity_mentions ---
    if total_mentions < _ENTITY_MENTIONS_CRITICAL:
        _crit(
            f"entity_mentions={total_mentions} — BELOW CRITICAL THRESHOLD ({_ENTITY_MENTIONS_CRITICAL}). "
            "Possible resolver / ingestion collapse."
        )
    elif total_mentions < _ENTITY_MENTIONS_WARNING:
        _warn(
            f"entity_mentions={total_mentions} — below warning threshold ({_ENTITY_MENTIONS_WARNING})."
        )

    # --- Check 2: Reddit entity_mentions ---
    if reddit_mentions == 0:
        if run_label == "evening":
            _crit(
                "reddit entity_mentions=0 after evening pipeline. "
                "Reddit ingestion likely failed or was fully blocked."
            )
        else:
            _warn(
                "reddit entity_mentions=0 after morning pipeline. "
                "Reddit may be blocked — watch evening run."
            )

    # --- Check 3: canonical_content_items by platform ---
    if reddit_items == 0:
        _warn(f"reddit canonical_content_items=0 today (collected_at={metrics.get('date','?')}).")
    if youtube_items < _CONTENT_ITEMS_YOUTUBE_WARNING:
        _warn(
            f"youtube canonical_content_items={youtube_items} — "
            f"below warning threshold ({_CONTENT_ITEMS_YOUTUBE_WARNING})."
        )
    if run_label == "evening" and total_items < _CONTENT_ITEMS_TOTAL_CRITICAL:
        _crit(
            f"total canonical_content_items={total_items} after evening pipeline — "
            f"below critical threshold ({_CONTENT_ITEMS_TOTAL_CRITICAL})."
        )

    # --- Check 4: public_safe_signals ---
    if run_label == "evening" and signals_today < _SIGNALS_WARNING:
        _warn(
            f"signals today={signals_today} — "
            f"below warning threshold ({_SIGNALS_WARNING}). Check aggregation / detector."
        )

    return level, issues


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_health_check(date: str, run_label: str) -> str:
    """Run all checks and log results. Returns overall level string."""
    url = get_database_url()
    engine = _make_engine(url)

    try:
        metrics = _fetch_metrics(engine, date)
    except Exception as exc:
        _log.error("PIPELINE_HEALTH_CRITICAL health_check_db_error=%s", exc)
        return "CRITICAL"

    metrics["date"] = date
    level, issues = _evaluate(metrics, run_label)

    # Always log the metrics summary
    _log.info(
        "pipeline_health_metrics date=%s run=%s "
        "entity_mentions=%d reddit_mentions=%d "
        "yt_items=%d reddit_items=%d total_items=%d signals=%d",
        date, run_label,
        metrics["total_mentions"],
        metrics["reddit_mentions"],
        metrics["youtube_items"],
        metrics["reddit_items"],
        metrics["total_items"],
        metrics["signals_today"],
    )

    for issue in issues:
        _log.warning("pipeline_health_issue %s", issue)

    marker = f"PIPELINE_HEALTH_{level}"
    _log.info(
        "%s date=%s run=%s issues=%d",
        marker, date, run_label, len(issues),
    )

    return level


def main() -> None:
    parser = argparse.ArgumentParser(description="PTI pipeline health check")
    parser.add_argument(
        "--date",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        help="Date to check (YYYY-MM-DD, default: today UTC)",
    )
    parser.add_argument(
        "--run-label",
        choices=["morning", "evening"],
        default="morning",
        help="Which pipeline run this is (affects thresholds)",
    )
    args = parser.parse_args()
    run_health_check(args.date, args.run_label)
    sys.exit(0)  # never fail the pipeline


if __name__ == "__main__":
    main()
