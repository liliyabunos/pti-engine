#!/usr/bin/env python3
from __future__ import annotations

"""
Orchestration job: detect signals and verify market state.

Runs detect_breakout_signals for a target date, then runs verify_market_state
to confirm no synthetic data leaked into the serving DB.

Must be run after run_aggregation.py completes for the same target date.

Usage:
    python -m perfume_trend_sdk.jobs.run_signals
    python -m perfume_trend_sdk.jobs.run_signals --date 2026-04-13
    python -m perfume_trend_sdk.jobs.run_signals --date 2026-04-12 --skip-verify

    # Run for last N days:
    python -m perfume_trend_sdk.jobs.run_signals --last-days 3

Exit codes:
    0  Signal detection and verification passed
    1  Signal detection failed or verification failed
"""

import argparse
import logging
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("run_signals")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run_module(module: str, extra_args: list[str] = (), *, dry_run: bool = False) -> bool:
    cmd = [sys.executable, "-m", module] + list(extra_args)
    display = " ".join(cmd)
    if dry_run:
        logger.info("[dry-run] %s", display)
        return True
    logger.info("Running: %s", display)
    try:
        result = subprocess.run(cmd, cwd=_PROJECT_ROOT, check=False, text=True)
        if result.returncode != 0:
            logger.error("Command exited %d: %s", result.returncode, display)
            return False
        return True
    except Exception as exc:
        logger.error("Command raised exception (%s): %s", exc, display)
        return False


def detect_signals(target_date: str, *, dry_run: bool = False) -> bool:
    logger.info("Detecting signals for date=%s", target_date)
    return _run_module(
        "perfume_trend_sdk.jobs.detect_breakout_signals",
        ["--date", target_date],
        dry_run=dry_run,
    )


def verify_state(*, dry_run: bool = False) -> bool:
    logger.info("Running market state verification")
    return _run_module(
        "perfume_trend_sdk.jobs.verify_market_state",
        dry_run=dry_run,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect signals and verify market state integrity."
    )
    parser.add_argument(
        "--date",
        action="append",
        dest="dates",
        metavar="YYYY-MM-DD",
        help="Target date(s) for signal detection (repeatable). Defaults to today.",
    )
    parser.add_argument(
        "--last-days",
        type=int,
        default=None,
        metavar="N",
        help="Run signal detection for the last N calendar days.",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip the verify_market_state step after signal detection.",
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

    logger.info("Signal detection run: dates=%s", dates)
    failures: list[str] = []

    for d in dates:
        ok = detect_signals(d, dry_run=args.dry_run)
        if not ok:
            failures.append(d)

    if failures:
        logger.error("Signal detection FAILED for dates: %s", ", ".join(failures))
        return 1

    if not args.skip_verify:
        ok = verify_state(dry_run=args.dry_run)
        if not ok:
            logger.error("Market state verification FAILED")
            return 1

    logger.info("Signal detection and verification COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
