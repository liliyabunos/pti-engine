#!/usr/bin/env python3
from __future__ import annotations

"""
Orchestration job: run daily metric aggregation.

Calls aggregate_daily_market_metrics for a target date (defaults to today).
Must be run after ingestion is complete for the target date.

Usage:
    python -m perfume_trend_sdk.jobs.run_aggregation
    python -m perfume_trend_sdk.jobs.run_aggregation --date 2026-04-13
    python -m perfume_trend_sdk.jobs.run_aggregation --date 2026-04-11 --date 2026-04-12

    # Run for last N days (e.g. catch up after a gap):
    python -m perfume_trend_sdk.jobs.run_aggregation --last-days 3

Exit codes:
    0  All dates succeeded
    1  One or more dates failed
"""

import argparse
import logging
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("run_aggregation")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _aggregate_date(target_date: str, *, dry_run: bool = False) -> bool:
    cmd = [
        sys.executable, "-m",
        "perfume_trend_sdk.jobs.aggregate_daily_market_metrics",
        "--date", target_date,
    ]
    display = " ".join(cmd)
    if dry_run:
        logger.info("[dry-run] %s", display)
        return True
    logger.info("Aggregating date=%s", target_date)
    try:
        result = subprocess.run(cmd, cwd=_PROJECT_ROOT, check=False, text=True)
        if result.returncode != 0:
            logger.error("Aggregation failed for date=%s (exit %d)", target_date, result.returncode)
            return False
        logger.info("Aggregation complete for date=%s", target_date)
        return True
    except Exception as exc:
        logger.error("Aggregation raised exception for date=%s: %s", target_date, exc)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run daily metric aggregation for one or more dates."
    )
    parser.add_argument(
        "--date",
        action="append",
        dest="dates",
        metavar="YYYY-MM-DD",
        help="Target date(s) to aggregate (repeatable). Defaults to today.",
    )
    parser.add_argument(
        "--last-days",
        type=int,
        default=None,
        metavar="N",
        help="Aggregate the last N calendar days (including today). Overrides --date.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing them",
    )
    args = parser.parse_args()

    today = date.today()

    if args.last_days:
        dates = [
            (today - timedelta(days=i)).isoformat()
            for i in range(args.last_days - 1, -1, -1)
        ]
    elif args.dates:
        dates = args.dates
    else:
        dates = [today.isoformat()]

    logger.info("Aggregation run: dates=%s", dates)
    failures: list[str] = []

    for d in dates:
        ok = _aggregate_date(d, dry_run=args.dry_run)
        if not ok:
            failures.append(d)

    if failures:
        logger.error("Aggregation FAILED for dates: %s", ", ".join(failures))
        return 1

    logger.info("Aggregation COMPLETE for all dates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
