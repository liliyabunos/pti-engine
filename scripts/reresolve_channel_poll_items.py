#!/usr/bin/env python3
"""Re-resolve channel_poll canonical_content_items using title-only input.

Fixes false-positive resolved_signals created when channel descriptions
contained boilerplate footer text matching perfume aliases (e.g. "cologne",
"Don", "11", "21" embedded in affiliate URLs).

What this script does:
  1. Reads canonical_content_items for the specified channel IDs where
     ingestion_method = 'channel_poll'.
  2. For each item, re-resolves using title-only (not description).
  3. Upserts resolved_signals (ON CONFLICT DO UPDATE overwrites old rows).
  4. Reports entity link counts before and after.

No YouTube API calls.  No aggregation.  No schema changes.

Usage:
    # Dry-run — show what would change without writing anything
    DATABASE_URL="..." python3 scripts/reresolve_channel_poll_items.py --dry-run

    # Target specific channels by their youtube channel_id (UC...)
    DATABASE_URL="..." python3 scripts/reresolve_channel_poll_items.py \\
        --channel-ids UCxxxxxxx UCyyyyyyy

    # Process ALL channel_poll items (no --channel-ids filter)
    DATABASE_URL="..." python3 scripts/reresolve_channel_poll_items.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2
import psycopg2.extras

from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import make_resolver

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


def _connect() -> psycopg2.extensions.connection:
    if not DATABASE_URL:
        print("[error] DATABASE_URL not set.", file=sys.stderr)
        sys.exit(1)
    return psycopg2.connect(DATABASE_URL)


def _load_items(
    conn: psycopg2.extensions.connection,
    channel_ids: Optional[List[str]],
) -> List[Dict[str, Any]]:
    """Load channel_poll content items from canonical_content_items."""
    base_sql = """
        SELECT
            id,
            title,
            text_content,
            source_account_id,
            source_account_handle,
            ingestion_method
        FROM canonical_content_items
        WHERE ingestion_method = 'channel_poll'
          AND source_platform = 'youtube'
    """
    params: list = []
    if channel_ids:
        base_sql += "  AND source_account_id = ANY(%s)\n"
        params.append(channel_ids)
    base_sql += "ORDER BY published_at DESC"

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(base_sql, params)
        return [dict(r) for r in cur.fetchall()]


def _count_existing_links(
    conn: psycopg2.extensions.connection,
    content_item_ids: List[str],
) -> int:
    """Count total resolved entity links for the given content_item_ids."""
    if not content_item_ids:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(SUM(jsonb_array_length(resolved_entities_json::jsonb)), 0)
            FROM resolved_signals
            WHERE content_item_id = ANY(%s)
            """,
            (content_item_ids,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0


def _upsert_resolved_signals(
    conn: psycopg2.extensions.connection,
    resolved_items: List[Dict[str, Any]],
) -> None:
    sql = """
        INSERT INTO resolved_signals (
            content_item_id,
            resolver_version,
            resolved_entities_json,
            unresolved_mentions_json,
            alias_candidates_json
        )
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (content_item_id) DO UPDATE SET
            resolver_version          = EXCLUDED.resolver_version,
            resolved_entities_json    = EXCLUDED.resolved_entities_json,
            unresolved_mentions_json  = EXCLUDED.unresolved_mentions_json,
            alias_candidates_json     = EXCLUDED.alias_candidates_json
    """
    rows = [
        (
            r["content_item_id"],
            r["resolver_version"],
            json.dumps(r.get("resolved_entities", []), ensure_ascii=False),
            json.dumps(r.get("unresolved_mentions", []), ensure_ascii=False),
            json.dumps(r.get("alias_candidates", []), ensure_ascii=False),
        )
        for r in resolved_items
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, rows, page_size=100)
    conn.commit()


# ---------------------------------------------------------------------------
# Per-channel reporting
# ---------------------------------------------------------------------------

def _report_links(
    conn: psycopg2.extensions.connection,
    channel_ids_filter: Optional[List[str]],
    label: str,
) -> Dict[str, int]:
    """Return {channel_handle: entity_link_count} for reporting."""
    base_sql = """
        SELECT
            cci.source_account_handle AS handle,
            cci.source_account_id     AS channel_id,
            COALESCE(SUM(jsonb_array_length(rs.resolved_entities_json::jsonb)), 0) AS links
        FROM canonical_content_items cci
        JOIN resolved_signals rs ON rs.content_item_id = cci.id
        WHERE cci.ingestion_method = 'channel_poll'
          AND cci.source_platform = 'youtube'
    """
    params: list = []
    if channel_ids_filter:
        base_sql += "  AND cci.source_account_id = ANY(%s)\n"
        params.append(channel_ids_filter)
    base_sql += "GROUP BY cci.source_account_handle, cci.source_account_id ORDER BY links DESC"

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(base_sql, params)
        rows = cur.fetchall()

    result = {}
    for r in rows:
        key = r["handle"] or r["channel_id"]
        result[key] = int(r["links"])
        print(f"  {label:6s} {key:<45} {int(r['links'])} entity links")
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-resolve channel_poll items using title-only input."
    )
    parser.add_argument(
        "--channel-ids", nargs="*",
        help="YouTube channel IDs (UC...) to re-resolve. Defaults to all channel_poll items."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print plan without writing resolved_signals."
    )
    parser.add_argument(
        "--resolver-db", default="outputs/pti.db",
        help="Resolver SQLite DB path (ignored when DATABASE_URL is set)"
    )
    args = parser.parse_args()

    conn = _connect()
    resolver = make_resolver(args.resolver_db)

    channel_ids = args.channel_ids or None

    print(f"[reresolve_channel_poll] dry_run={args.dry_run}")
    if channel_ids:
        print(f"[reresolve_channel_poll] channel filter: {channel_ids}")
    else:
        print("[reresolve_channel_poll] no channel filter — processing ALL channel_poll items")

    # Before counts
    print("\n--- BEFORE ---")
    _report_links(conn, channel_ids, "BEFORE")

    # Load items
    items = _load_items(conn, channel_ids)
    print(f"\n[reresolve_channel_poll] loaded {len(items)} channel_poll items to re-resolve")

    if not items:
        print("[reresolve_channel_poll] Nothing to do.")
        conn.close()
        return

    content_item_ids = [r["id"] for r in items]
    links_before = _count_existing_links(conn, content_item_ids)
    print(f"[reresolve_channel_poll] existing entity links: {links_before}")

    if args.dry_run:
        # Show what the title-only resolver would produce for the first few items
        print("\n--- DRY-RUN SAMPLE (first 10 items) ---")
        for item in items[:10]:
            title_only_item = {**item, "text_content": item.get("title") or ""}
            result = resolver.resolve_content_item(title_only_item)
            entities = result.get("resolved_entities", [])
            print(
                f"  title={item.get('title', '')[:60]!r:<65} "
                f"→ {len(entities)} links: "
                + ", ".join(e["canonical_name"][:30] for e in entities[:3])
            )
        print(f"\n[reresolve_channel_poll] Dry run complete. Would re-resolve {len(items)} items.")
        conn.close()
        return

    # Re-resolve using title-only
    resolved_items = []
    for item in items:
        title_only_item = {**item, "text_content": item.get("title") or ""}
        result = resolver.resolve_content_item(title_only_item)
        # Use the reresolve tag so we can distinguish from original
        result["resolver_version"] = result["resolver_version"] + "-channel-title-only"
        resolved_items.append(result)

    _upsert_resolved_signals(conn, resolved_items)

    links_after = _count_existing_links(conn, content_item_ids)
    links_removed = links_before - links_after

    print("\n--- AFTER ---")
    _report_links(conn, channel_ids, "AFTER")

    print(f"\n[reresolve_channel_poll] Summary:")
    print(f"  items re-resolved:   {len(items)}")
    print(f"  entity links before: {links_before}")
    print(f"  entity links after:  {links_after}")
    print(f"  false positives removed: {links_removed}")
    print(f"  resolver_version tag: *-channel-title-only")
    print(f"\n[reresolve_channel_poll] Done. Do NOT aggregate yet — pending user approval.")

    conn.close()


if __name__ == "__main__":
    main()
