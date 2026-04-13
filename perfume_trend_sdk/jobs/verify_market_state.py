from __future__ import annotations

"""
Job: verify_market_state

Runs MarketVerifier for a target date against the configured database.
Exits with code 0 if all checks pass, 1 on any failure.

Usage:
    python3 -m perfume_trend_sdk.jobs.verify_market_state --date 2026-04-10

    # Skip API checks (DB checks only):
    python3 -m perfume_trend_sdk.jobs.verify_market_state --date 2026-04-10 --no-api

    # Machine-readable output:
    python3 -m perfume_trend_sdk.jobs.verify_market_state --date 2026-04-10 --json
"""

import argparse
import json
import logging
import sys
from datetime import date

from perfume_trend_sdk.db.market.models import Base
from perfume_trend_sdk.db.market.session import _make_engine, get_database_url
from perfume_trend_sdk.verification.market_verifier import MarketVerifier

logger = logging.getLogger(__name__)


def run(
    target_date: str,
    *,
    with_api: bool = True,
    allow_demo: bool = False,
) -> "VerificationResult":  # noqa: F821 — avoid circular import at module level
    """Programmatic entry point for embedding verification in other jobs.

    Args:
        target_date: ISO date string (YYYY-MM-DD).
        with_api:    Whether to spin up a TestClient and run API checks.
        allow_demo:  When True, demo/synthetic data only warns instead of failing.

    Returns:
        VerificationResult.
    """
    from perfume_trend_sdk.verification.market_verifier import VerificationResult  # noqa

    url = get_database_url()
    engine = _make_engine(url)
    Base.metadata.create_all(engine)

    from sqlalchemy.orm import sessionmaker
    Session_ = sessionmaker(bind=engine)

    test_client = None
    if with_api:
        try:
            from fastapi.testclient import TestClient
            from perfume_trend_sdk.api.main import app
            test_client = TestClient(app)
        except Exception as exc:
            logger.warning(
                "verify_market_state_api_client_failed exc=%s — API checks skipped", exc
            )

    with Session_() as session:
        verifier = MarketVerifier(db=session, test_client=test_client, allow_demo=allow_demo)
        return verifier.verify(target_date)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Verify market state integrity for a target date."
    )
    p.add_argument(
        "--date",
        default=None,
        help="ISO date YYYY-MM-DD (default: today)",
    )
    p.add_argument(
        "--no-api",
        action="store_true",
        help="Skip API checks (DB checks only)",
    )
    p.add_argument(
        "--allow-demo",
        action="store_true",
        default=False,
        help=(
            "When set, synthetic/demo data only triggers a warning instead of a failure. "
            "Default: False — any demo data causes verification to FAIL."
        ),
    )
    p.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit result as JSON to stdout",
    )
    return p


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    target_date = args.date or date.today().isoformat()

    logger.info("verify_market_state_started date=%s", target_date)

    result = run(target_date, with_api=not args.no_api, allow_demo=args.allow_demo)

    if args.json_output:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        width = 68
        print(f"\n{'=' * width}")
        print(f"  Market Verification — {target_date}")
        print(f"{'=' * width}\n")
        for check in result.passed_checks:
            print(f"  PASS  {check}")
        for warn in result.warnings:
            print(f"  WARN  {warn}")
        for fail in result.failed_checks:
            print(f"  FAIL  {fail}")

        # Inline demo_stats block when present
        demo = result.metrics.get("demo_stats")
        if demo:
            print()
            print(f"  Data purity ({target_date}):")
            print(f"    total items : {demo['total_items']}")
            print(f"    real        : {demo['real_items']} ({demo['real_percentage']}%)"
                  f"  [{demo['real_channels_count']} channels]")
            print(f"    synthetic   : {demo['demo_items']} ({demo['demo_percentage']}%)")
            if demo["demo_by_platform"]:
                breakdown = "  ".join(
                    f"{k}={v}" for k, v in demo["demo_by_platform"].items()
                )
                print(f"    breakdown   : {breakdown}")

        print(f"\n  {result.to_dict()['summary']}")
        print(f"{'=' * width}\n")

    logger.info(
        "verify_market_state_completed date=%s passed=%s failures=%d",
        target_date,
        result.passed,
        len(result.failed_checks),
    )

    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
