#!/usr/bin/env python3
from __future__ import annotations

"""
Orchestration job: ingest all active sources.

Runs YouTube and Reddit ingestion sequentially. Each source is treated as
an independent unit — a failure in one source is logged but does not abort
the other.

Usage (direct):
    python -m perfume_trend_sdk.jobs.run_ingestion

Options:
    --sources youtube reddit   Sources to run (default: all active)
    --lookback-days N          Days of history to fetch (default: env or 2)
    --max-results N            Max results per YouTube query (default: env or 50)
    --dry-run                  Print commands without executing them

Environment variables (override defaults):
    INGEST_YT_MAX_RESULTS       YouTube max results per query
    INGEST_YT_LOOKBACK_DAYS     YouTube lookback window
    INGEST_REDDIT_LOOKBACK_DAYS Reddit lookback window

Exit codes:
    0  YouTube succeeded (Reddit failure is non-fatal)
    1  YouTube failed (pipeline must not aggregate without primary source data)
"""

import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("run_ingestion")

# ---------------------------------------------------------------------------
# Resolve project root so subprocess calls work regardless of cwd
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: list[str], *, dry_run: bool = False) -> bool:
    """Run a subprocess command. Returns True on success."""
    display = " ".join(str(c) for c in cmd)
    if dry_run:
        logger.info("[dry-run] %s", display)
        return True
    logger.info("Running: %s", display)
    try:
        result = subprocess.run(
            cmd,
            cwd=_PROJECT_ROOT,
            check=False,
            text=True,
        )
        if result.returncode != 0:
            logger.error("Command exited %d: %s", result.returncode, display)
            return False
        return True
    except Exception as exc:
        logger.error("Command raised exception (%s): %s", exc, display)
        return False


def ingest_youtube(*, max_results: int, lookback_days: int, dry_run: bool) -> bool:
    return _run(
        [
            sys.executable, "scripts/ingest_youtube.py",
            "--max-results", str(max_results),
            "--lookback-days", str(lookback_days),
        ],
        dry_run=dry_run,
    )


def ingest_reddit(*, lookback_days: int, dry_run: bool) -> bool:
    return _run(
        [
            sys.executable, "scripts/ingest_reddit.py",
            "--lookback-days", str(lookback_days),
        ],
        dry_run=dry_run,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest all active sources into the market engine DB."
    )
    parser.add_argument(
        "--sources",
        nargs="*",
        default=["youtube", "reddit"],
        metavar="SRC",
        help="Sources to run: youtube reddit (default: all)",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=int(os.environ.get("INGEST_YT_MAX_RESULTS", 50)),
        metavar="N",
        help="Max YouTube results per query (default: INGEST_YT_MAX_RESULTS or 50)",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=None,
        metavar="N",
        help="Days of history to fetch for all sources (overrides per-source env vars)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing them",
    )
    args = parser.parse_args()

    sources = {s.lower() for s in (args.sources or [])}
    started_at = datetime.now(timezone.utc)
    logger.info("Ingestion run started at %s | sources=%s", started_at.isoformat(), sorted(sources))

    failures: list[str] = []

    if "youtube" in sources:
        yt_lookback = args.lookback_days or int(os.environ.get("INGEST_YT_LOOKBACK_DAYS", 2))
        logger.info("--- YouTube ingestion (lookback=%dd, max_results=%d) ---", yt_lookback, args.max_results)
        ok = ingest_youtube(
            max_results=args.max_results,
            lookback_days=yt_lookback,
            dry_run=args.dry_run,
        )
        if not ok:
            failures.append("youtube")

    reddit_nonfatal_failure = False
    if "reddit" in sources:
        reddit_lookback = args.lookback_days or int(os.environ.get("INGEST_REDDIT_LOOKBACK_DAYS", 1))
        logger.info("--- Reddit ingestion (lookback=%dd) ---", reddit_lookback)
        ok = ingest_reddit(lookback_days=reddit_lookback, dry_run=args.dry_run)
        if not ok:
            # Reddit failure is non-fatal. Railway IP blocks are an expected transient condition.
            # Aggregation must still run on YouTube data even when Reddit is blocked.
            # CRITICAL/WARNING logs from ingest_reddit.py remain fully visible above this line.
            reddit_nonfatal_failure = True
            logger.warning(
                "[run_ingestion] WARNING: Reddit ingestion failed; continuing because Reddit is non-critical."
            )

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()

    if failures:
        logger.error(
            "Ingestion run FAILED for: %s  (elapsed=%.1fs)",
            ", ".join(failures), elapsed,
        )
        return 1

    if reddit_nonfatal_failure:
        logger.warning(
            "Ingestion run COMPLETE with Reddit failure (non-fatal)  (elapsed=%.1fs)", elapsed,
        )
    else:
        logger.info("Ingestion run COMPLETE  (elapsed=%.1fs)", elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
