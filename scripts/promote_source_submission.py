#!/usr/bin/env python3
"""
Source Submission Operator Bridge — S1.

Controlled promotion workflow:
  source_submissions (pending) → [operator review] → youtube_channels (active)
  → existing pipeline picks it up from youtube_channels

Usage examples:

  # List reviewable submissions
  python3 scripts/promote_source_submission.py --list-pending
  python3 scripts/promote_source_submission.py --list-pending --limit 20

  # Count pending
  python3 scripts/promote_source_submission.py --count-pending

  # Dry-run promote (default — no DB writes)
  python3 scripts/promote_source_submission.py --id 5 --quality-tier tier_4 --category reviewer --priority low

  # Apply promote (writes to DB)
  python3 scripts/promote_source_submission.py --id 5 --quality-tier tier_4 --category reviewer --priority low --apply

  # Reject a submission
  python3 scripts/promote_source_submission.py --id 5 --reject --reason "not fragrance related" --apply

  # Mark as needing manual resolution (handle/@/video/shorts URLs)
  python3 scripts/promote_source_submission.py --id 5 --needs-manual-resolve --reason "YouTube @handle — needs channel_id resolution" --apply

  # Mark as platform pending (TikTok / Instagram / Reddit)
  python3 scripts/promote_source_submission.py --id 5 --platform-pending --reason "Platform not connected to ingestion yet" --apply

Security guarantees:
  - No submitted URL is executed or fetched
  - No YouTube API calls (S1 scope)
  - Only direct /channel/UC... URLs are promotable; handles/videos/shorts are rejected
  - Only writes to youtube_channels and source_submissions — no market/score tables touched
  - All SQL queries are parameterized
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Constants (aligned with manage_channels.py)
# ---------------------------------------------------------------------------

VALID_QUALITY_TIERS = {"tier_1", "tier_2", "tier_3", "tier_4", "blocked", "unrated"}
VALID_CATEGORIES = {"reviewer", "collector", "beauty", "brand", "retailer", "community", "unknown"}
VALID_PRIORITIES = {"high", "medium", "low"}

# UC... channel ID — same as manage_channels.py
_CHANNEL_ID_RE = re.compile(r"UC[a-zA-Z0-9_-]{22}")

# Statuses shown in --list-pending
_REVIEWABLE_STATUSES = ("pending", "needs_manual_resolve", "platform_pending")

# Only pending submissions can be promoted to youtube_channels
_PROMOTABLE_STATUSES = ("pending",)

# Bare YouTube hosts (after www./m. prefix stripping)
_YOUTUBE_BARE_HOSTS = frozenset({"youtube.com"})


# ---------------------------------------------------------------------------
# URL classification — pure functions, no DB, no network
# ---------------------------------------------------------------------------

def _strip_host_prefix(netloc: str) -> str:
    """Remove www. and m. prefixes from a netloc string."""
    return re.sub(r"^(?:www\.|m\.)", "", netloc.lower())


def _classify_youtube_url_type(url: str) -> str:
    """Classify a YouTube URL into a promotion-relevant type.

    Returns:
      'channel_direct'  — /channel/UC... with extractable UC channel_id (S1 promotable)
      'handle'          — /@handle, /c/name, /user/name (needs API resolution)
      'video'           — /watch?v= or youtu.be/... (needs API resolution)
      'shorts'          — /shorts/ (needs API resolution)
      'other'           — other YouTube-hosted path or non-YouTube URL
    """
    try:
        parsed = urlparse(url)
        host = _strip_host_prefix(parsed.netloc)
        path = parsed.path
        query = parsed.query
    except Exception:
        return "other"

    if host == "youtu.be":
        return "video"

    if host not in _YOUTUBE_BARE_HOSTS:
        return "other"

    if "/channel/" in path and _CHANNEL_ID_RE.search(path):
        return "channel_direct"
    if path.startswith("/@") or "/c/" in path or "/user/" in path:
        return "handle"
    if "/shorts/" in path:
        return "shorts"
    if "/watch" in path or "v=" in query:
        return "video"
    return "other"


def _extract_channel_id(url: str) -> Optional[str]:
    """Extract UC... channel_id from a /channel/UC... URL path only.

    Returns None for handles, video URLs, shorts, or youtu.be links.
    Does not make any network calls.
    """
    try:
        path = urlparse(url).path
    except Exception:
        return None
    if "/channel/" not in path:
        return None
    m = _CHANNEL_ID_RE.search(path)
    return m.group(0) if m else None


def validate_for_promotion(submission: dict) -> tuple[Optional[str], Optional[str]]:
    """Pure validation: can this submission dict be promoted?

    Returns (error_message, channel_id).
    error_message is None if the submission is valid for promotion.
    """
    if submission.get("status") not in _PROMOTABLE_STATUSES:
        return (
            f"status is {submission.get('status')!r}. Only 'pending' submissions can be promoted.",
            None,
        )
    if submission.get("platform") != "youtube":
        return (
            f"platform is {submission.get('platform')!r}. Only YouTube channels are promotable. "
            f"Use --platform-pending for other platforms.",
            None,
        )
    url = submission.get("normalized_url", "")
    url_type = _classify_youtube_url_type(url)
    if url_type != "channel_direct":
        return (
            f"URL type is {url_type!r}. Only direct /channel/UC... URLs are promotable in S1. "
            f"Use --needs-manual-resolve for handles, videos, and shorts.",
            None,
        )
    channel_id = _extract_channel_id(url)
    if not channel_id:
        return ("Could not extract a valid UC... channel_id from the URL.", None)
    return (None, channel_id)


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------

def _connect() -> psycopg2.extensions.connection:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print(
            "[error] DATABASE_URL not set. This script requires a PostgreSQL connection.",
            file=sys.stderr,
        )
        sys.exit(1)
    return psycopg2.connect(database_url)


# ---------------------------------------------------------------------------
# DB helpers (parameterized — no string concatenation)
# ---------------------------------------------------------------------------

def _load_submission(
    cur: psycopg2.extensions.cursor, submission_id: int
) -> Optional[dict]:
    cur.execute(
        """
        SELECT id, raw_url, normalized_url, platform, status,
               submitted_by_email, created_at
        FROM source_submissions
        WHERE id = %s
        """,
        (submission_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "raw_url": row[1],
        "normalized_url": row[2],
        "platform": row[3],
        "status": row[4],
        "submitted_by_email": row[5],
        "created_at": row[6],
    }


def _update_submission_status(
    cur: psycopg2.extensions.cursor,
    submission_id: int,
    status: str,
    notes: Optional[str] = None,
) -> None:
    """Update source_submissions status, reviewed_at, reviewer_notes."""
    cur.execute(
        """
        UPDATE source_submissions
        SET status = %s,
            reviewed_at = %s,
            reviewer_notes = %s
        WHERE id = %s
        """,
        (status, datetime.now(timezone.utc), notes, submission_id),
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list_pending(args: argparse.Namespace, conn: psycopg2.extensions.connection) -> None:
    limit = args.limit or 50
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(
            """
            SELECT id, platform, status, normalized_url, submitted_by_email, created_at
            FROM source_submissions
            WHERE status = ANY(%s)
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (list(_REVIEWABLE_STATUSES), limit),
        )
        rows = cur.fetchall()

    if not rows:
        print("No reviewable submissions.")
        return

    print(
        f"{'ID':<6} {'PLATFORM':<12} {'STATUS':<22} "
        f"{'SUBMITTED BY':<30} {'CREATED':<18} NORMALIZED URL"
    )
    print("-" * 140)
    for r in rows:
        created = r["created_at"].strftime("%Y-%m-%d %H:%M") if r["created_at"] else "-"
        email = (r["submitted_by_email"] or "-")[:28]
        print(
            f"{r['id']:<6} {(r['platform'] or '-'):<12} {r['status']:<22} "
            f"{email:<30} {created:<18} {r['normalized_url'] or '-'}"
        )
    print(f"\nTotal: {len(rows)} submission(s)")


def cmd_count_pending(conn: psycopg2.extensions.connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM source_submissions WHERE status = ANY(%s)",
            (list(_REVIEWABLE_STATUSES),),
        )
        count = cur.fetchone()[0]
    noun = "submission" if count == 1 else "submissions"
    print(f"{count} pending source {noun}")


def cmd_promote(args: argparse.Namespace, conn: psycopg2.extensions.connection) -> None:
    apply = args.apply
    submission_id = args.id
    quality_tier = (args.quality_tier or "tier_4").strip().lower()
    category = (args.category or "reviewer").strip().lower()
    priority = (args.priority or "low").strip().lower()

    if quality_tier not in VALID_QUALITY_TIERS:
        print(
            f"[error] Invalid quality_tier: {quality_tier!r}. "
            f"Choose from: {sorted(VALID_QUALITY_TIERS)}",
            file=sys.stderr,
        )
        sys.exit(1)
    if category not in VALID_CATEGORIES:
        print(
            f"[error] Invalid category: {category!r}. "
            f"Choose from: {sorted(VALID_CATEGORIES)}",
            file=sys.stderr,
        )
        sys.exit(1)
    if priority not in VALID_PRIORITIES:
        print(
            f"[error] Invalid priority: {priority!r}. "
            f"Choose from: {sorted(VALID_PRIORITIES)}",
            file=sys.stderr,
        )
        sys.exit(1)

    with conn.cursor() as cur:
        submission = _load_submission(cur, submission_id)

    if submission is None:
        print(f"[error] Submission #{submission_id} not found.", file=sys.stderr)
        sys.exit(1)

    print(f"Submission #{submission['id']}")
    print(f"  Status:   {submission['status']}")
    print(f"  Platform: {submission['platform'] or '-'}")
    print(f"  URL:      {submission['normalized_url']}")
    print(f"  Email:    {submission['submitted_by_email'] or '-'}")
    print()

    # Pure validation — no DB
    error, channel_id = validate_for_promotion(submission)
    if error:
        print(f"[error] Cannot promote: {error}", file=sys.stderr)
        sys.exit(1)

    print(f"  channel_id:    {channel_id}")
    print(f"  quality_tier:  {quality_tier}")
    print(f"  category:      {category}")
    print(f"  priority:      {priority}")
    print()

    # Check if channel already in youtube_channels
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, status FROM youtube_channels WHERE channel_id = %s",
            (channel_id,),
        )
        existing_channel = cur.fetchone()

    if existing_channel:
        print(
            f"[skip] Channel {channel_id} is already in youtube_channels "
            f"(id={existing_channel[0]}, status={existing_channel[1]})."
        )
        if apply:
            with conn.cursor() as cur:
                _update_submission_status(
                    cur, submission_id, "already_tracked",
                    f"Channel {channel_id} already present in youtube_channels.",
                )
            conn.commit()
            print(f"[ok] Submission #{submission_id} → already_tracked")
        else:
            print(
                "[dry-run] Would update source_submissions.status → already_tracked. "
                "Pass --apply to write."
            )
        return

    # Announce planned action
    tag = "apply" if apply else "dry-run"
    print(f"[{tag}] Would insert into youtube_channels:")
    print(f"  channel_id={channel_id}")
    print(f"  quality_tier={quality_tier}, category={category}, priority={priority}")
    print(f"  status=active, added_by=operator_script")
    print(f"[{tag}] Would update source_submissions #{submission_id} → promoted")

    if not apply:
        print("\n[dry-run] No changes written. Pass --apply to execute.")
        return

    # Write: youtube_channels INSERT + source_submissions UPDATE (single tx)
    new_yt_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO youtube_channels
                (id, channel_id, quality_tier, category, priority, status,
                 added_at, added_by, notes)
            VALUES (%s, %s, %s, %s, %s, 'active', NOW(), 'operator_script', %s)
            """,
            (
                new_yt_id,
                channel_id,
                quality_tier,
                category,
                priority,
                f"Promoted from source_submissions #{submission_id}",
            ),
        )
        _update_submission_status(
            cur, submission_id, "promoted",
            "Promoted to youtube_channels by operator script.",
        )
    conn.commit()

    print(f"\n[ok] Channel {channel_id} added to youtube_channels (id={new_yt_id})")
    print(f"[ok] Submission #{submission_id} → promoted")
    print("[ok] Pipeline will pick this channel up on its next poll cycle.")


def cmd_reject(args: argparse.Namespace, conn: psycopg2.extensions.connection) -> None:
    apply = args.apply
    submission_id = args.id
    reason = (args.reason or "").strip() or "Rejected by operator."

    with conn.cursor() as cur:
        submission = _load_submission(cur, submission_id)

    if submission is None:
        print(f"[error] Submission #{submission_id} not found.", file=sys.stderr)
        sys.exit(1)

    tag = "apply" if apply else "dry-run"
    print(f"Submission #{submission['id']} — {submission['normalized_url']}")
    print(f"[{tag}] Would set status=rejected, reviewer_notes={reason!r}")

    if not apply:
        print("\n[dry-run] Pass --apply to write.")
        return

    with conn.cursor() as cur:
        _update_submission_status(cur, submission_id, "rejected", reason)
    conn.commit()
    print(f"[ok] Submission #{submission_id} → rejected")


def cmd_needs_manual_resolve(
    args: argparse.Namespace, conn: psycopg2.extensions.connection
) -> None:
    apply = args.apply
    submission_id = args.id
    reason = (args.reason or "").strip() or (
        "YouTube handle or video URL — requires channel_id resolution via YouTube API."
    )

    with conn.cursor() as cur:
        submission = _load_submission(cur, submission_id)

    if submission is None:
        print(f"[error] Submission #{submission_id} not found.", file=sys.stderr)
        sys.exit(1)

    tag = "apply" if apply else "dry-run"
    print(f"Submission #{submission['id']} — {submission['normalized_url']}")
    print(f"[{tag}] Would set status=needs_manual_resolve")
    print(f"  Reason: {reason}")

    if not apply:
        print("\n[dry-run] Pass --apply to write.")
        return

    with conn.cursor() as cur:
        _update_submission_status(cur, submission_id, "needs_manual_resolve", reason)
    conn.commit()
    print(f"[ok] Submission #{submission_id} → needs_manual_resolve")


def cmd_platform_pending(
    args: argparse.Namespace, conn: psycopg2.extensions.connection
) -> None:
    apply = args.apply
    submission_id = args.id
    reason = (args.reason or "").strip() or (
        "Platform not connected to ingestion pipeline yet."
    )

    with conn.cursor() as cur:
        submission = _load_submission(cur, submission_id)

    if submission is None:
        print(f"[error] Submission #{submission_id} not found.", file=sys.stderr)
        sys.exit(1)

    tag = "apply" if apply else "dry-run"
    print(f"Submission #{submission['id']} — {submission['normalized_url']}")
    print(f"[{tag}] Would set status=platform_pending")
    print(f"  Reason: {reason}")

    if not apply:
        print("\n[dry-run] Pass --apply to write.")
        return

    with conn.cursor() as cur:
        _update_submission_status(cur, submission_id, "platform_pending", reason)
    conn.commit()
    print(f"[ok] Submission #{submission_id} → platform_pending")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Source Submission Operator Bridge — S1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Defaults are dry-run — pass --apply to write changes to the database.\n"
            "Promote only inserts into youtube_channels. No market/score tables are touched."
        ),
    )

    # Info commands (no --id needed)
    parser.add_argument(
        "--list-pending", action="store_true",
        help="List pending, needs_manual_resolve, and platform_pending submissions",
    )
    parser.add_argument(
        "--count-pending", action="store_true",
        help="Print count of reviewable submissions",
    )

    # ID-based operations
    parser.add_argument("--id", type=int, metavar="SUBMISSION_ID",
                        help="Source submission ID to act on")

    # Action modifiers (for --id operations)
    # Default action when --id is given alone = promote (dry-run)
    parser.add_argument("--reject", action="store_true",
                        help="Mark submission as rejected")
    parser.add_argument("--needs-manual-resolve", action="store_true",
                        dest="needs_manual_resolve",
                        help="Mark as needing manual channel_id resolution")
    parser.add_argument("--platform-pending", action="store_true",
                        dest="platform_pending",
                        help="Mark as platform pending (non-YouTube platforms)")

    # Promote parameters
    parser.add_argument("--quality-tier", default="tier_4",
                        choices=sorted(VALID_QUALITY_TIERS),
                        dest="quality_tier",
                        help="Quality tier for youtube_channels insert (default: tier_4)")
    parser.add_argument("--category", default="reviewer",
                        choices=sorted(VALID_CATEGORIES),
                        help="Channel category (default: reviewer)")
    parser.add_argument("--priority", default="low",
                        choices=sorted(VALID_PRIORITIES),
                        help="Channel priority (default: low)")

    # Shared
    parser.add_argument("--reason", help="Reason text for reject/needs-manual-resolve/platform-pending")
    parser.add_argument("--limit", type=int, default=50,
                        help="Max rows for --list-pending (default: 50)")
    parser.add_argument("--apply", action="store_true",
                        help="Write changes to DB. Without this flag all operations are dry-run only.")

    args = parser.parse_args()

    # Dispatch
    if args.list_pending:
        conn = _connect()
        try:
            cmd_list_pending(args, conn)
        finally:
            conn.close()

    elif args.count_pending:
        conn = _connect()
        try:
            cmd_count_pending(conn)
        finally:
            conn.close()

    elif args.id is not None:
        conn = _connect()
        try:
            if args.reject:
                cmd_reject(args, conn)
            elif args.needs_manual_resolve:
                cmd_needs_manual_resolve(args, conn)
            elif args.platform_pending:
                cmd_platform_pending(args, conn)
            else:
                # Default: promote (dry-run unless --apply)
                cmd_promote(args, conn)
        finally:
            conn.close()

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
