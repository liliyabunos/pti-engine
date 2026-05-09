#!/usr/bin/env python3
from __future__ import annotations

"""
SC1.2D — TikTok browser-rendered public profile evaluation script.

EVALUATION ONLY — diagnostic, read-only, never wired into the pipeline.

Usage:
    python3 -m perfume_trend_sdk.scripts.evaluate_tiktok_browser_profile
    python3 -m perfume_trend_sdk.scripts.evaluate_tiktok_browser_profile --handle rawscents
    python3 -m perfume_trend_sdk.scripts.evaluate_tiktok_browser_profile --limit 3
    python3 -m perfume_trend_sdk.scripts.evaluate_tiktok_browser_profile --handle rawscents --headed

Hard guarantees:
  - Never writes to canonical_content_items
  - Never writes to entity_mentions
  - Never updates creator_platform_accounts.last_checked_at
  - Never changes creator status
  - Never logs in / sends cookies

Output:
  - Structured JSON report per creator printed to stdout
  - Summary + recommended decision printed to stderr
"""

import argparse
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s %(name)s  %(message)s",
    stream=sys.stderr,
)
_log = logging.getLogger("sc1.2d")


# ---------------------------------------------------------------------------
# DB helpers — read only
# ---------------------------------------------------------------------------

def _load_handles_from_db(limit: int) -> List[str]:
    """Return active TikTok creator handles from creator_platform_accounts."""
    try:
        from sqlalchemy import create_engine, text as sa_text
    except ImportError:
        _log.error("sqlalchemy not installed")
        return []

    url = os.environ.get("DATABASE_URL")
    if not url:
        _log.warning("DATABASE_URL not set — cannot load handles from DB")
        return []

    engine = create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(sa_text("""
            SELECT platform_handle
            FROM creator_platform_accounts
            WHERE platform = 'tiktok'
              AND status IN ('active', 'pending_review')
            ORDER BY status = 'active' DESC, follower_count DESC NULLS LAST
            LIMIT :limit
        """), {"limit": limit}).fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def _build_summary(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(results)
    rendered_ok = sum(1 for r in results if r["rendered_success"])
    login_wall = sum(1 for r in results if r["login_wall_detected"])
    captcha = sum(1 for r in results if r["captcha_or_block_detected"])
    any_videos = sum(1 for r in results if r["video_urls_found"] > 0)
    total_videos = sum(r["video_urls_found"] for r in results)
    avg_render = (
        sum(r["render_time_seconds"] for r in results) / total if total else 0
    )
    extraction_methods = {}
    for r in results:
        m = r["extraction_method"]
        extraction_methods[m] = extraction_methods.get(m, 0) + 1

    # Decision logic
    if captcha > 0 or login_wall > 0:
        decision = "B"
        decision_reason = (
            "TikTok showed captcha/login wall — browser extraction not viable "
            "without workarounds. Rely on Layer 1 / manual intake."
        )
    elif rendered_ok == 0:
        decision = "B"
        decision_reason = "No profiles rendered successfully."
    elif any_videos == 0:
        decision = "C"
        decision_reason = (
            "Profiles rendered but no video URLs extracted. "
            "Requires compliance review before pursuing further approaches."
        )
    elif any_videos > 0 and rendered_ok == total and captcha == 0:
        decision = "A"
        decision_reason = (
            "Browser rendering works and video URLs extracted successfully. "
            "Proceed to SC1.2E production-safe browser worker design."
        )
    else:
        decision = "C"
        decision_reason = "Partial success — requires compliance review."

    return {
        "total_handles_tested": total,
        "rendered_successfully": rendered_ok,
        "login_wall_detected_count": login_wall,
        "captcha_or_block_count": captcha,
        "handles_with_video_urls": any_videos,
        "total_video_urls_found": total_videos,
        "avg_render_time_seconds": round(avg_render, 2),
        "extraction_methods": extraction_methods,
        "recommended_decision": decision,
        "decision_options": {
            "A": "Proceed to SC1.2E production-safe browser worker",
            "B": "Do not proceed — rely on Layer 1 / manual TikTok URL intake",
            "C": "Requires separate compliance review before decision",
        },
        "decision_reason": decision_reason,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="SC1.2D — TikTok browser-rendered profile evaluation (read-only)"
    )
    parser.add_argument(
        "--handle",
        default=None,
        help="Specific TikTok handle to evaluate (overrides --limit DB lookup)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=2,
        help="Number of creators to pull from DB when no --handle given (default: 2)",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run browser in headed (visible) mode for debugging",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write JSON report to this file (in addition to stdout)",
    )
    args = parser.parse_args()

    from perfume_trend_sdk.ingest.tiktok_browser_extractor import evaluate_profile

    # Resolve handles
    if args.handle:
        handles = [args.handle.lstrip("@")]
    else:
        handles = _load_handles_from_db(args.limit)
        if not handles:
            _log.error(
                "No handles found. Set DATABASE_URL or pass --handle <handle>."
            )
            sys.exit(1)

    _log.info("[sc1.2d] Evaluating %d handle(s): %s", len(handles), handles)
    _log.info("[sc1.2d] Mode: headless=%s", not args.headed)
    _log.info("[sc1.2d] DB writes: NONE (evaluation only)")

    results = []
    for handle in handles:
        _log.info("[sc1.2d] ── Evaluating @%s ──", handle)
        result = evaluate_profile(handle, headless=not args.headed)
        d = result.to_dict()
        results.append(d)
        _log.info(
            "[sc1.2d] @%s rendered=%s captcha=%s login_wall=%s videos=%d method=%s time=%.1fs",
            handle,
            d["rendered_success"],
            d["captcha_or_block_detected"],
            d["login_wall_detected"],
            d["video_urls_found"],
            d["extraction_method"],
            d["render_time_seconds"],
        )
        if d.get("error_message"):
            _log.warning("[sc1.2d] @%s error: %s", handle, d["error_message"])
        # Polite delay between profiles
        if handle != handles[-1]:
            time.sleep(3)

    summary = _build_summary(results)

    report = {
        "evaluation": "SC1.2D — TikTok browser-rendered profile evaluation",
        "summary": summary,
        "per_handle": results,
    }

    # Print JSON to stdout
    print(json.dumps(report, indent=2))

    # Optionally write to file
    if args.output:
        with open(args.output, "w") as fh:
            json.dump(report, fh, indent=2)
        _log.info("[sc1.2d] Report written to: %s", args.output)

    # Print human-readable summary to stderr
    print("\n" + "=" * 68, file=sys.stderr)
    print("  SC1.2D EVALUATION SUMMARY", file=sys.stderr)
    print("=" * 68, file=sys.stderr)
    for k, v in summary.items():
        if k not in ("decision_options", "decision_reason"):
            print(f"  {k}: {v}", file=sys.stderr)
    print(file=sys.stderr)
    print(f"  RECOMMENDED DECISION: {summary['recommended_decision']}", file=sys.stderr)
    print(f"  {summary['decision_options'][summary['recommended_decision']]}", file=sys.stderr)
    print(f"  Reason: {summary['decision_reason']}", file=sys.stderr)
    print("=" * 68, file=sys.stderr)


if __name__ == "__main__":
    main()
