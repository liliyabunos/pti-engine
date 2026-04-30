#!/usr/bin/env python3
"""
YouTube Channel Registry — management CLI.

Usage examples:
  # Add a single channel
  python3 scripts/manage_channels.py --add UCxxxxxx --title "Fragrance Therapy" \
      --quality-tier tier_1 --category reviewer --priority high

  # List channels (optionally filtered)
  python3 scripts/manage_channels.py --list
  python3 scripts/manage_channels.py --list --status active --quality-tier tier_1

  # Disable / enable a channel
  python3 scripts/manage_channels.py --disable UCxxxxxx
  python3 scripts/manage_channels.py --enable UCxxxxxx

  # Update tier or priority
  python3 scripts/manage_channels.py --update-tier UCxxxxxx --quality-tier tier_2
  python3 scripts/manage_channels.py --update-priority UCxxxxxx --priority low

  # Bulk import from CSV  (columns: channel_id, title, quality_tier, category, priority, notes)
  python3 scripts/manage_channels.py --import-csv channels.csv

  # Verify attribution join health
  python3 scripts/manage_channels.py --verify
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_QUALITY_TIERS = {"tier_1", "tier_2", "tier_3", "tier_4", "blocked", "unrated"}
VALID_CATEGORIES = {
    "reviewer", "collector", "beauty", "brand", "retailer", "community", "unknown"
}
VALID_PRIORITIES = {"high", "medium", "low"}
VALID_STATUSES = {"active", "paused", "blocked", "retired"}

# UC... format
_CHANNEL_ID_RE = re.compile(r"^UC[a-zA-Z0-9_-]{22}$")


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------

def _connect() -> psycopg2.extensions.connection:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("[error] DATABASE_URL not set. This script requires a Postgres connection.", file=sys.stderr)
        sys.exit(1)
    return psycopg2.connect(database_url)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.lower().strip())


def _validate_channel_id(channel_id: str) -> str:
    channel_id = channel_id.strip()
    if not _CHANNEL_ID_RE.match(channel_id):
        print(f"[error] Invalid channel_id format: {channel_id!r}. Must match UC + 22 chars.", file=sys.stderr)
        sys.exit(1)
    return channel_id


def _validate_tier(tier: str) -> str:
    tier = tier.strip().lower()
    if tier not in VALID_QUALITY_TIERS:
        print(f"[error] Invalid quality_tier: {tier!r}. Choose from: {sorted(VALID_QUALITY_TIERS)}", file=sys.stderr)
        sys.exit(1)
    return tier


def _validate_category(cat: str) -> str:
    cat = cat.strip().lower()
    if cat not in VALID_CATEGORIES:
        print(f"[warn] Unknown category: {cat!r}. Allowed: {sorted(VALID_CATEGORIES)}. Storing anyway.", file=sys.stderr)
    return cat


def _validate_priority(pri: str) -> str:
    pri = pri.strip().lower()
    if pri not in VALID_PRIORITIES:
        print(f"[error] Invalid priority: {pri!r}. Choose from: {sorted(VALID_PRIORITIES)}", file=sys.stderr)
        sys.exit(1)
    return pri


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_add(
    args: argparse.Namespace,
    conn: psycopg2.extensions.connection,
) -> None:
    channel_id = _validate_channel_id(args.add)
    quality_tier = _validate_tier(args.quality_tier or "unrated")
    category = _validate_category(args.category or "unknown")
    priority = _validate_priority(args.priority or "medium")
    title = (args.title or "").strip() or None
    normalized = _normalize_title(title) if title else None
    handle = (args.handle or "").strip() or None
    notes = (args.notes or "").strip() or None

    with conn.cursor() as cur:
        # Duplicate check
        cur.execute("SELECT id, status FROM youtube_channels WHERE channel_id = %s", (channel_id,))
        existing = cur.fetchone()
        if existing:
            print(f"[skip] Channel {channel_id} already in registry (id={existing[0]}, status={existing[1]}).")
            return

        # Fuzzy title warning
        if normalized:
            cur.execute(
                "SELECT channel_id, title FROM youtube_channels WHERE normalized_title = %s",
                (normalized,),
            )
            dup = cur.fetchone()
            if dup:
                print(
                    f"[warn] A channel with a similar title already exists: "
                    f"{dup[1]!r} ({dup[0]}). Adding anyway — verify this is a different channel."
                )

        cur.execute(
            """
            INSERT INTO youtube_channels
                (id, channel_id, handle, title, normalized_title,
                 quality_tier, category, priority, status,
                 added_at, added_by, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active', NOW(), 'manual', %s)
            """,
            (
                str(uuid.uuid4()),
                channel_id,
                handle,
                title,
                normalized,
                quality_tier,
                category,
                priority,
                notes,
            ),
        )
        conn.commit()
        print(
            f"[ok] Added channel {channel_id} "
            f"(tier={quality_tier}, category={category}, priority={priority})"
        )


def cmd_list(
    args: argparse.Namespace,
    conn: psycopg2.extensions.connection,
) -> None:
    clauses = ["1=1"]
    params: list = []

    if args.status:
        clauses.append("status = %s")
        params.append(args.status)
    if args.quality_tier:
        clauses.append("quality_tier = %s")
        params.append(args.quality_tier)
    if args.category:
        clauses.append("category = %s")
        params.append(args.category)
    if args.priority:
        clauses.append("priority = %s")
        params.append(args.priority)

    where = " AND ".join(clauses)

    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(
            f"""
            SELECT channel_id, handle, title, quality_tier, category, priority,
                   status, last_polled_at, last_poll_status, consecutive_empty_polls,
                   last_video_count, added_at
            FROM youtube_channels
            WHERE {where}
            ORDER BY priority DESC, last_polled_at NULLS FIRST, added_at
            """,
            params,
        )
        rows = cur.fetchall()

    if not rows:
        print("No channels match the filter.")
        return

    print(
        f"{'CHANNEL_ID':<26} {'TIER':<10} {'CAT':<12} {'PRI':<7} {'STATUS':<10} "
        f"{'LAST_POLL':<22} {'POLL_ST':<10} {'TITLE'}"
    )
    print("-" * 120)
    for r in rows:
        last_poll = r["last_polled_at"].strftime("%Y-%m-%d %H:%M") if r["last_polled_at"] else "never"
        print(
            f"{r['channel_id']:<26} {r['quality_tier']:<10} {r['category']:<12} "
            f"{r['priority']:<7} {r['status']:<10} {last_poll:<22} "
            f"{(r['last_poll_status'] or '-'):<10} {r['title'] or '-'}"
        )
    print(f"\nTotal: {len(rows)} channel(s)")


def cmd_disable(
    args: argparse.Namespace,
    conn: psycopg2.extensions.connection,
) -> None:
    channel_id = _validate_channel_id(args.disable)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE youtube_channels SET status = 'paused' WHERE channel_id = %s RETURNING id",
            (channel_id,),
        )
        if cur.rowcount == 0:
            print(f"[warn] Channel {channel_id} not found in registry.")
        else:
            conn.commit()
            print(f"[ok] Channel {channel_id} paused.")


def cmd_enable(
    args: argparse.Namespace,
    conn: psycopg2.extensions.connection,
) -> None:
    channel_id = _validate_channel_id(args.enable)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE youtube_channels SET status = 'active' WHERE channel_id = %s RETURNING id",
            (channel_id,),
        )
        if cur.rowcount == 0:
            print(f"[warn] Channel {channel_id} not found in registry.")
        else:
            conn.commit()
            print(f"[ok] Channel {channel_id} enabled.")


def cmd_update_tier(
    args: argparse.Namespace,
    conn: psycopg2.extensions.connection,
) -> None:
    channel_id = _validate_channel_id(args.update_tier)
    tier = _validate_tier(args.quality_tier or "unrated")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE youtube_channels SET quality_tier = %s WHERE channel_id = %s RETURNING id",
            (tier, channel_id),
        )
        if cur.rowcount == 0:
            print(f"[warn] Channel {channel_id} not found in registry.")
        else:
            conn.commit()
            print(f"[ok] Channel {channel_id} quality_tier → {tier}.")


def cmd_update_priority(
    args: argparse.Namespace,
    conn: psycopg2.extensions.connection,
) -> None:
    channel_id = _validate_channel_id(args.update_priority)
    priority = _validate_priority(args.priority or "medium")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE youtube_channels SET priority = %s WHERE channel_id = %s RETURNING id",
            (priority, channel_id),
        )
        if cur.rowcount == 0:
            print(f"[warn] Channel {channel_id} not found in registry.")
        else:
            conn.commit()
            print(f"[ok] Channel {channel_id} priority → {priority}.")


def cmd_import_csv(
    args: argparse.Namespace,
    conn: psycopg2.extensions.connection,
) -> None:
    """
    CSV format (header required):
      channel_id, title, quality_tier, category, priority, notes
    Optional columns: handle
    """
    path = args.import_csv
    if not os.path.exists(path):
        print(f"[error] File not found: {path}", file=sys.stderr)
        sys.exit(1)

    added = 0
    skipped = 0
    warned = 0

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"channel_id"}
        if not required.issubset(set(reader.fieldnames or [])):
            print(f"[error] CSV must have at minimum: {required}", file=sys.stderr)
            sys.exit(1)

        for i, row in enumerate(reader, start=2):
            channel_id = (row.get("channel_id") or "").strip()
            if not channel_id:
                print(f"[warn] Row {i}: empty channel_id — skipped.")
                skipped += 1
                continue

            if not _CHANNEL_ID_RE.match(channel_id):
                print(f"[warn] Row {i}: invalid channel_id format {channel_id!r} — skipped.")
                skipped += 1
                continue

            quality_tier = _validate_tier(row.get("quality_tier") or "unrated")
            category = _validate_category(row.get("category") or "unknown")
            priority = _validate_priority(row.get("priority") or "medium")
            title = (row.get("title") or "").strip() or None
            handle = (row.get("handle") or "").strip() or None
            notes = (row.get("notes") or "").strip() or None
            normalized = _normalize_title(title) if title else None

            with conn.cursor() as cur:
                cur.execute("SELECT id FROM youtube_channels WHERE channel_id = %s", (channel_id,))
                if cur.fetchone():
                    skipped += 1
                    continue

                if normalized:
                    cur.execute(
                        "SELECT channel_id FROM youtube_channels WHERE normalized_title = %s",
                        (normalized,),
                    )
                    dup = cur.fetchone()
                    if dup:
                        print(
                            f"[warn] Row {i}: similar title already in registry for {dup[0]}. "
                            f"Adding {channel_id} anyway."
                        )
                        warned += 1

                cur.execute(
                    """
                    INSERT INTO youtube_channels
                        (id, channel_id, handle, title, normalized_title,
                         quality_tier, category, priority, status,
                         added_at, added_by, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active', NOW(), 'csv_import', %s)
                    """,
                    (
                        str(uuid.uuid4()),
                        channel_id,
                        handle,
                        title,
                        normalized,
                        quality_tier,
                        category,
                        priority,
                        notes,
                    ),
                )
                added += 1

    conn.commit()
    print(f"[ok] Import complete: {added} added, {skipped} skipped, {warned} title-collision warnings.")


def cmd_verify(conn: psycopg2.extensions.connection) -> None:
    """Check attribution join health between youtube_channels and canonical_content_items."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM youtube_channels")
        total_channels = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM youtube_channels WHERE status = 'active'")
        active_channels = cur.fetchone()[0]

        cur.execute(
            """
            SELECT COUNT(*) FROM canonical_content_items
            WHERE source_platform = 'youtube'
            """
        )
        total_yt_items = cur.fetchone()[0]

        cur.execute(
            """
            SELECT COUNT(*) FROM canonical_content_items
            WHERE source_platform = 'youtube'
              AND ingestion_method = 'channel_poll'
            """
        )
        channel_polled_items = cur.fetchone()[0]

        cur.execute(
            """
            SELECT COUNT(DISTINCT cci.source_account_id)
            FROM canonical_content_items cci
            JOIN youtube_channels yc ON yc.channel_id = cci.source_account_id
            WHERE cci.source_platform = 'youtube'
            """
        )
        matched_channels = cur.fetchone()[0]

        cur.execute(
            """
            SELECT yc.channel_id, yc.title, COUNT(cci.id) AS items
            FROM youtube_channels yc
            JOIN canonical_content_items cci ON cci.source_account_id = yc.channel_id
            WHERE cci.source_platform = 'youtube'
            GROUP BY yc.channel_id, yc.title
            ORDER BY items DESC
            LIMIT 10
            """
        )
        top_channels = cur.fetchall()

    print("=" * 60)
    print("YouTube Channel Registry — Verification Report")
    print("=" * 60)
    print(f"  Registered channels (total):  {total_channels}")
    print(f"  Active channels:              {active_channels}")
    print(f"  YouTube content items total:  {total_yt_items}")
    print(f"  Channel-polled items:         {channel_polled_items}")
    print(f"  Channels with matched items:  {matched_channels}")
    print()

    if top_channels:
        print("Top channels by ingested item count:")
        for ch_id, title, count in top_channels:
            print(f"  {ch_id}  {(title or '-')[:40]:<42} {count} items")
    else:
        print("No attribution matches yet (channel_id join returned 0 rows).")

    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="YouTube Channel Registry management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Mutually exclusive primary actions
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--add", metavar="CHANNEL_ID", help="Add a channel to the registry")
    action.add_argument("--list", action="store_true", help="List channels")
    action.add_argument("--disable", metavar="CHANNEL_ID", help="Pause a channel (sets status=paused)")
    action.add_argument("--enable", metavar="CHANNEL_ID", help="Re-enable a channel (sets status=active)")
    action.add_argument("--update-tier", metavar="CHANNEL_ID", help="Update quality_tier for a channel")
    action.add_argument("--update-priority", metavar="CHANNEL_ID", help="Update priority for a channel")
    action.add_argument("--import-csv", metavar="FILE", help="Bulk import channels from CSV")
    action.add_argument("--verify", action="store_true", help="Verify attribution join health")

    # Shared modifiers
    parser.add_argument("--title", help="Channel title (for --add)")
    parser.add_argument("--handle", help="Channel handle e.g. @FragranceTherapy (for --add)")
    parser.add_argument("--quality-tier", choices=sorted(VALID_QUALITY_TIERS),
                        help="Quality tier (for --add / --update-tier / --list filter)")
    parser.add_argument("--category", choices=sorted(VALID_CATEGORIES),
                        help="Channel category (for --add / --list filter)")
    parser.add_argument("--priority", choices=sorted(VALID_PRIORITIES),
                        help="Priority (for --add / --update-priority / --list filter)")
    parser.add_argument("--status", choices=sorted(VALID_STATUSES),
                        help="Status filter (for --list)")
    parser.add_argument("--notes", help="Free-text notes (for --add)")

    args = parser.parse_args()
    conn = _connect()

    try:
        if args.add:
            cmd_add(args, conn)
        elif args.list:
            cmd_list(args, conn)
        elif args.disable:
            cmd_disable(args, conn)
        elif args.enable:
            cmd_enable(args, conn)
        elif args.update_tier:
            cmd_update_tier(args, conn)
        elif args.update_priority:
            cmd_update_priority(args, conn)
        elif args.import_csv:
            cmd_import_csv(args, conn)
        elif args.verify:
            cmd_verify(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
