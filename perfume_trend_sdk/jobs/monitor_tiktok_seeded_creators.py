from __future__ import annotations

"""
SC1.2C — TikTok Seeded Creator Monitoring Worker.

Reads active TikTok creators from creator_platform_accounts and:
  1. Verifies creator profiles are still reachable and public.
  2. Updates follower_count and last_checked_at metadata.
  3. Logs clearly that video list discovery requires an authenticated method
     (NOT implemented in SC1.2C — simple HTTP returns empty video list).

KILL SWITCH: TIKTOK_PUBLIC_MONITORING_ENABLED=false (default) exits immediately.

Usage:
    python3 -m perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators
    python3 -m perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators --limit 5
    python3 -m perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators --handle rawscents --dry-run
    python3 -m perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators --force

SC1.2C Limitation (verified 2026-05-08):
    TikTok profile pages served via simple HTTP always return an empty
    itemList in the SSR JSON. Video discovery requires authenticated API
    access or an approved browser-based method. This will be addressed in
    a future phase. This worker currently performs profile reachability
    checks and metadata updates only.

Log markers:
    TIKTOK_MONITOR_DISABLED       — kill switch active, safe exit
    TIKTOK_MONITOR_STARTED        — run beginning
    TIKTOK_MONITOR_CREATOR_OK     — profile reachable, metadata updated
    TIKTOK_MONITOR_CREATOR_WARNING — reachable but video list unavailable
    TIKTOK_MONITOR_CREATOR_ERROR  — fetch failed or profile unreachable
    TIKTOK_MONITOR_COMPLETE       — run finished with summary counts
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

from perfume_trend_sdk.db.market.session import _make_engine, get_database_url
from perfume_trend_sdk.ingest.tiktok_page_parser import parse_profile_page
from sqlalchemy import text
from sqlalchemy.orm import Session

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(message)s",
    stream=sys.stdout,
)
_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_DEFAULT_SLEEP_SECONDS = 4.0   # polite gap between requests
_DEFAULT_TIMEOUT = 12          # seconds
_SKIP_CHECKED_WITHIN_HOURS = 24


# ---------------------------------------------------------------------------
# HTTP fetch (no auth, no cookies, no automation)
# ---------------------------------------------------------------------------

def _fetch_profile_page(handle: str, timeout: int = _DEFAULT_TIMEOUT) -> tuple[int, str]:
    """
    Fetch TikTok creator profile page via plain HTTPS GET.

    Returns (http_status_code, html_body).
    Raises on network error (caller catches).
    """
    url = f"https://www.tiktok.com/@{handle}"
    resp = requests.get(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=timeout,
        allow_redirects=True,
    )
    return resp.status_code, resp.text


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_active_creators(db: Session, limit: int, handle: Optional[str]) -> list[dict]:
    """Load active TikTok creators from creator_platform_accounts."""
    if handle:
        # Allow targeting any status when handle is explicit (for dry-run debugging)
        rows = db.execute(
            text("""
                SELECT id, platform_handle, status, last_checked_at,
                       follower_count, notes
                FROM creator_platform_accounts
                WHERE platform = 'tiktok' AND platform_handle = :handle
                LIMIT 1
            """),
            {"handle": handle},
        ).fetchall()
    else:
        rows = db.execute(
            text("""
                SELECT id, platform_handle, status, last_checked_at,
                       follower_count, notes
                FROM creator_platform_accounts
                WHERE platform = 'tiktok' AND status = 'active'
                ORDER BY last_checked_at ASC NULLS FIRST
                LIMIT :limit
            """),
            {"limit": limit},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def _should_skip(creator: dict, force: bool) -> bool:
    """Return True if this creator was checked recently and --force not set."""
    if force:
        return False
    last = creator.get("last_checked_at")
    if last is None:
        return False
    if hasattr(last, "tzinfo") and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    elif isinstance(last, str):
        try:
            last = datetime.fromisoformat(last)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
        except ValueError:
            return False
    cutoff = datetime.now(timezone.utc) - timedelta(hours=_SKIP_CHECKED_WITHIN_HOURS)
    return last > cutoff


def _update_creator_metadata(
    db: Session,
    creator_id: int,
    *,
    follower_count: Optional[int],
    status: Optional[str],
    last_checked_at: str,
) -> None:
    updates = ["last_checked_at = :last_checked_at"]
    params: dict = {
        "id": creator_id,
        "last_checked_at": last_checked_at,
    }
    if follower_count is not None:
        updates.append("follower_count = :follower_count")
        params["follower_count"] = follower_count
    if status is not None:
        updates.append("status = :status")
        params["status"] = status
    updates.append("updated_at = :last_checked_at")

    db.execute(
        text(f"UPDATE creator_platform_accounts SET {', '.join(updates)} WHERE id = :id"),
        params,
    )


def _write_audit(
    db: Session,
    handle: str,
    action: str,
    note: Optional[str],
    old_status: Optional[str] = None,
    new_status: Optional[str] = None,
) -> None:
    db.execute(
        text("""
            INSERT INTO creator_watchlist_audit_log
                (platform, platform_handle, action, old_status, new_status, source_method, note, created_at)
            VALUES
                ('tiktok', :handle, :action, :old_status, :new_status, 'public_creator_monitoring', :note, :now)
        """),
        {
            "handle": handle,
            "action": action,
            "old_status": old_status,
            "new_status": new_status,
            "note": note,
            "now": _now_iso(),
        },
    )


# ---------------------------------------------------------------------------
# Per-creator processing
# ---------------------------------------------------------------------------

def _process_creator(
    db: Session,
    creator: dict,
    *,
    dry_run: bool,
    counters: dict,
) -> None:
    handle = creator["platform_handle"]
    creator_id = creator["id"]
    old_status = creator["status"]

    _log.info("TIKTOK_MONITOR_CREATOR_START handle=@%s", handle)

    try:
        http_status, html = _fetch_profile_page(handle)
    except Exception as exc:
        _log.warning(
            "TIKTOK_MONITOR_CREATOR_ERROR handle=@%s fetch_error=%s",
            handle, exc,
        )
        counters["errors"] += 1
        if not dry_run:
            try:
                _write_audit(db, handle, "monitor_fetch_error", str(exc)[:500],
                             old_status=old_status, new_status=old_status)
                _update_creator_metadata(
                    db, creator_id,
                    follower_count=None,
                    status=None,
                    last_checked_at=_now_iso(),
                )
                db.commit()
            except Exception as db_exc:
                _log.warning("DB update after fetch error failed: %s", db_exc)
                db.rollback()
        return

    result = parse_profile_page(handle, html)
    result.http_status = http_status

    if not result.reachable:
        # Profile unreachable or private
        _log.warning(
            "TIKTOK_MONITOR_CREATOR_ERROR handle=@%s http=%d tiktok_status=%s error=%s",
            handle, http_status, result.status_code, result.error,
        )
        counters["errors"] += 1
        if not dry_run:
            try:
                new_status = "error" if old_status == "active" else old_status
                _write_audit(db, handle, "monitor_profile_unreachable",
                             f"http={http_status} tiktok_status={result.status_code}: {result.error}",
                             old_status=old_status, new_status=new_status)
                _update_creator_metadata(
                    db, creator_id,
                    follower_count=None,
                    status=new_status if new_status != old_status else None,
                    last_checked_at=_now_iso(),
                )
                db.commit()
            except Exception as db_exc:
                _log.warning("DB update after unreachable failed: %s", db_exc)
                db.rollback()
        return

    # Profile is reachable — log metadata
    _log.info(
        "TIKTOK_MONITOR_CREATOR_OK handle=@%s followers=%s videos=%s verified=%s",
        handle, result.follower_count, result.video_count, result.verified,
    )
    counters["creators_checked"] += 1

    # SC1.2C limitation: video list not available via simple HTTP
    if result.video_list_requires_auth:
        _log.warning(
            "TIKTOK_MONITOR_CREATOR_WARNING handle=@%s "
            "video_list_unavailable=true "
            "reason='itemList empty in SSR JSON — video discovery requires "
            "authenticated API or approved browser-based method (not in SC1.2C)'",
            handle,
        )

    # Note: videos_inserted stays 0 in SC1.2C — no video discovery implemented
    # This counter is reserved for the future phase when video discovery is viable.

    if not dry_run:
        try:
            _write_audit(
                db, handle, "monitor_profile_check",
                f"followers={result.follower_count} videos={result.video_count} "
                f"verified={result.verified} video_list_requires_auth={result.video_list_requires_auth}",
                old_status=old_status, new_status=old_status,
            )
            _update_creator_metadata(
                db, creator_id,
                follower_count=result.follower_count,
                status=None,  # don't change status on successful check
                last_checked_at=_now_iso(),
            )
            db.commit()
        except Exception as db_exc:
            _log.warning("DB update after profile check failed: %s", db_exc)
            db.rollback()


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------

def run(
    *,
    limit: int,
    force: bool,
    handle: Optional[str],
    dry_run: bool,
    sleep_seconds: float,
) -> dict:
    """
    Execute monitoring run. Returns counters dict.
    Exits early (safe) if TIKTOK_PUBLIC_MONITORING_ENABLED != 'true'.
    """
    enabled = os.environ.get("TIKTOK_PUBLIC_MONITORING_ENABLED", "false").lower()
    if enabled != "true":
        _log.info(
            "TIKTOK_MONITOR_DISABLED "
            "TIKTOK_PUBLIC_MONITORING_ENABLED=%r — worker exiting safely. "
            "Set TIKTOK_PUBLIC_MONITORING_ENABLED=true to enable.",
            os.environ.get("TIKTOK_PUBLIC_MONITORING_ENABLED", "false"),
        )
        return {"disabled": True}

    _log.info(
        "TIKTOK_MONITOR_STARTED limit=%d force=%s handle=%s dry_run=%s sleep=%.1fs",
        limit, force, handle or "all_active", dry_run, sleep_seconds,
    )

    counters = {
        "creators_checked": 0,
        "creators_skipped": 0,
        "videos_found": 0,       # reserved for future phase
        "videos_inserted": 0,    # reserved for future phase
        "duplicates_skipped": 0, # reserved for future phase
        "errors": 0,
    }

    url = get_database_url()
    engine = _make_engine(url)

    with Session(engine) as db:
        creators = _load_active_creators(db, limit=limit, handle=handle)

        if not creators:
            _log.info("TIKTOK_MONITOR_COMPLETE no active creators found")
            return counters

        _log.info("Loaded %d creator(s) for processing", len(creators))

        for i, creator in enumerate(creators):
            ch = creator["platform_handle"]

            # Skip if not explicitly targeted and status is not active
            if not handle and creator.get("status") != "active":
                _log.info("skip handle=@%s status=%s", ch, creator.get("status"))
                counters["creators_skipped"] += 1
                continue

            if _should_skip(creator, force):
                _log.info(
                    "skip handle=@%s last_checked_at=%s (within %dh — use --force to override)",
                    ch, creator.get("last_checked_at"), _SKIP_CHECKED_WITHIN_HOURS,
                )
                counters["creators_skipped"] += 1
                continue

            _process_creator(db, creator, dry_run=dry_run, counters=counters)

            # Polite sleep between requests (skip after last creator)
            if i < len(creators) - 1:
                time.sleep(sleep_seconds)

    _log.info(
        "TIKTOK_MONITOR_COMPLETE "
        "creators_checked=%d creators_skipped=%d "
        "videos_found=%d videos_inserted=%d duplicates_skipped=%d errors=%d "
        "dry_run=%s",
        counters["creators_checked"],
        counters["creators_skipped"],
        counters["videos_found"],
        counters["videos_inserted"],
        counters["duplicates_skipped"],
        counters["errors"],
        dry_run,
    )
    return counters


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SC1.2C TikTok seeded creator monitoring worker"
    )
    parser.add_argument("--limit", type=int, default=25,
                        help="Max creators to process per run (default 25)")
    parser.add_argument("--force", action="store_true",
                        help="Ignore last_checked_at and recheck all active creators")
    parser.add_argument("--handle", type=str, default=None,
                        help="Target a specific handle (any status, useful for dry-run)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and parse but write nothing to DB")
    parser.add_argument("--date", type=str, default=None,
                        help="Unused in SC1.2C — reserved for future batch modes")
    parser.add_argument("--sleep-seconds", type=float, default=_DEFAULT_SLEEP_SECONDS,
                        help=f"Sleep between requests (default {_DEFAULT_SLEEP_SECONDS}s)")
    args = parser.parse_args()

    result = run(
        limit=args.limit,
        force=args.force,
        handle=args.handle,
        dry_run=args.dry_run,
        sleep_seconds=args.sleep_seconds,
    )
    sys.exit(0)  # never exit non-zero — monitoring failure must not stop the pipeline


if __name__ == "__main__":
    main()
