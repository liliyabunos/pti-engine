#!/usr/bin/env python3
from __future__ import annotations

"""
SC1.3 — Multi-field resolver replay / backtest report.

Loads canonical_content_items for a given date range and compares:
  - Old resolver: single-field (text_content only)
  - New resolver: multi-field (platform-weighted fields, MULTI_FIELD_RESOLVER_ENABLED=true)

Safety: this script never writes to the database. Read-only.

Usage:
    python3 scripts/replay_multi_field_resolver.py --start 2026-05-04 --end 2026-05-07
    python3 scripts/replay_multi_field_resolver.py --start 2026-05-04 --end 2026-05-07 --platform youtube
    python3 scripts/replay_multi_field_resolver.py --start 2026-05-04 --end 2026-05-07 --limit 500

Output:
    Console report with old/new resolved counts, regression checks, changed
    matches, false-positive risk examples.

    JSON summary written to outputs/replay_mf_resolver_<start>_<end>.json
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# DB query
# ---------------------------------------------------------------------------

def _load_items(
    *,
    start_date: str,
    end_date: str,
    platform: Optional[str],
    limit: int,
) -> List[Dict[str, Any]]:
    """Load canonical_content_items for the replay window."""
    from sqlalchemy import create_engine, text as sa_text

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("[replay] ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    engine = create_engine(url)

    platform_filter = "AND source_platform = :platform" if platform else ""
    query = sa_text(f"""
        SELECT
            id,
            source_platform,
            title,
            text_content,
            hashtags_json,
            tiktok_layer,
            mention_weight_override,
            referencing_context,
            collected_at
        FROM canonical_content_items
        WHERE DATE(collected_at::timestamptz) BETWEEN :start AND :end
          {platform_filter}
        ORDER BY collected_at DESC
        LIMIT :limit
    """)

    params = {"start": start_date, "end": end_date, "limit": limit}
    if platform:
        params["platform"] = platform

    with engine.connect() as conn:
        rows = conn.execute(query, params).fetchall()

    items = []
    for row in rows:
        hashtags = []
        if row[4]:  # hashtags_json
            try:
                hashtags = json.loads(row[4]) if isinstance(row[4], str) else (row[4] or [])
            except Exception:
                hashtags = []
        items.append({
            "id": row[0],
            "source_platform": row[1],
            "title": row[2],
            "text_content": row[3],
            "hashtags": hashtags,
            "tiktok_layer": row[5],
            "mention_weight_override": float(row[6]) if row[6] is not None else None,
            "referencing_context": row[7],
            "collected_at": str(row[8]),
        })

    return items


# ---------------------------------------------------------------------------
# Resolver construction
# ---------------------------------------------------------------------------

def _make_resolvers():
    """Return (old_resolver, new_resolver_fn) pair."""
    from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import make_resolver

    resolver = make_resolver()
    return resolver


# ---------------------------------------------------------------------------
# Old resolver (single-field)
# ---------------------------------------------------------------------------

def _resolve_old(resolver, item: Dict[str, Any]) -> List[str]:
    """Run old single-field resolver. Returns list of canonical_name strings."""
    text = item.get("text_content") or ""
    if not text:
        return []
    matches = resolver.resolve_text(text)
    return [m["canonical_name"] for m in matches]


# ---------------------------------------------------------------------------
# New resolver (multi-field)
# ---------------------------------------------------------------------------

def _resolve_new(resolver, item: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Run new multi-field resolver.
    Returns list of dicts with canonical_name, matched_field, final_confidence.
    """
    from perfume_trend_sdk.resolvers.perfume_identity.multi_field_resolver import (
        extract_signal_from_content_item,
        resolve_multi_field,
    )

    signal = extract_signal_from_content_item(item)
    mf_matches = resolve_multi_field(resolver, signal)
    return [
        {
            "canonical_name": m.canonical_name,
            "matched_field": m.matched_field,
            "final_confidence": round(m.final_confidence, 4),
            "all_fields": m.all_fields,
            "platform_key": m.platform_key,
        }
        for m in mf_matches
    ]


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def run_replay(
    *,
    start_date: str,
    end_date: str,
    platform: Optional[str],
    limit: int,
    top_n: int,
) -> Dict[str, Any]:
    print(f"\n[replay] Loading items: {start_date} → {end_date}", end="")
    if platform:
        print(f" platform={platform}", end="")
    print(f" limit={limit}")

    items = _load_items(
        start_date=start_date,
        end_date=end_date,
        platform=platform,
        limit=limit,
    )
    print(f"[replay] {len(items)} items loaded")

    if not items:
        print("[replay] No items found. Exiting.")
        return {}

    resolver = _make_resolvers()

    # Per-platform stats
    stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {
        "total": 0,
        "old_resolved": 0,
        "new_resolved": 0,
        "gained": 0,    # new resolved, old did not
        "lost": 0,      # old resolved, new did not
        "changed": 0,   # different entity set
    })

    changed_examples: List[Dict[str, Any]] = []
    false_positive_risk: List[Dict[str, Any]] = []
    gain_examples: List[Dict[str, Any]] = []

    for item in items:
        plat = item.get("source_platform", "unknown")
        old_names = set(_resolve_old(resolver, item))
        new_results = _resolve_new(resolver, item)
        new_names = {r["canonical_name"] for r in new_results}

        s = stats[plat]
        s["total"] += 1
        if old_names:
            s["old_resolved"] += 1
        if new_names:
            s["new_resolved"] += 1

        gained = new_names - old_names
        lost = old_names - new_names
        changed = bool(gained or lost)

        if gained:
            s["gained"] += 1
        if lost:
            s["lost"] += 1
        if changed:
            s["changed"] += 1

        # Collect change examples
        if changed and len(changed_examples) < top_n:
            changed_examples.append({
                "id": item["id"],
                "platform": plat,
                "title": (item.get("title") or "")[:80],
                "text_snippet": (item.get("text_content") or "")[:80],
                "old": sorted(old_names),
                "new": sorted(new_names),
                "gained": sorted(gained),
                "lost": sorted(lost),
                "new_details": new_results,
            })

        # False positive risk: new resolves with low confidence from weak field
        for r in new_results:
            if (
                r["canonical_name"] not in old_names
                and r["matched_field"] in ("title", "description")
                and r["final_confidence"] < 0.5
                and len(false_positive_risk) < top_n
            ):
                false_positive_risk.append({
                    "id": item["id"],
                    "platform": plat,
                    "entity": r["canonical_name"],
                    "matched_field": r["matched_field"],
                    "final_confidence": r["final_confidence"],
                    "title": (item.get("title") or "")[:80],
                    "context": (item.get("text_content") or "")[:80],
                })

        # Gain examples (new finds a match, old did not)
        if gained and r.get("matched_field") and len(gain_examples) < top_n:
            for r2 in new_results:
                if r2["canonical_name"] in gained and len(gain_examples) < top_n:
                    gain_examples.append({
                        "id": item["id"],
                        "platform": plat,
                        "entity": r2["canonical_name"],
                        "matched_field": r2["matched_field"],
                        "final_confidence": r2["final_confidence"],
                        "title": (item.get("title") or "")[:80],
                    })

    # Aggregate totals
    total = sum(s["total"] for s in stats.values())
    old_total = sum(s["old_resolved"] for s in stats.values())
    new_total = sum(s["new_resolved"] for s in stats.values())
    total_gained = sum(s["gained"] for s in stats.values())
    total_lost = sum(s["lost"] for s in stats.values())
    total_changed = sum(s["changed"] for s in stats.values())

    # Regression check
    youtube_stats = stats.get("youtube", {})
    reddit_stats = stats.get("reddit", {})
    youtube_lost = youtube_stats.get("lost", 0)
    reddit_lost = reddit_stats.get("lost", 0)

    regression_youtube = youtube_lost > 0
    regression_reddit = reddit_lost > 0
    safe_to_enable = not regression_youtube and not regression_reddit

    # Print report
    print("\n" + "=" * 68)
    print("  MULTI-FIELD RESOLVER REPLAY REPORT")
    print(f"  Date range:  {start_date} → {end_date}")
    print(f"  Items loaded: {total}")
    print("=" * 68)

    print("\n  OVERALL COUNTS")
    print(f"  Old resolver resolved:  {old_total:5d} / {total}")
    print(f"  New resolver resolved:  {new_total:5d} / {total}")
    print(f"  Items with gains:       {total_gained:5d}  (new found, old missed)")
    print(f"  Items with losses:      {total_lost:5d}  (old found, new missed)")
    print(f"  Items with any change:  {total_changed:5d}")

    print("\n  PER-PLATFORM BREAKDOWN")
    for plat, s in sorted(stats.items()):
        if s["total"] == 0:
            continue
        print(
            f"  {plat:15s}  total={s['total']:4d}  old={s['old_resolved']:4d}"
            f"  new={s['new_resolved']:4d}"
            f"  gained={s['gained']:3d}  lost={s['lost']:3d}"
        )

    print("\n  REGRESSION CHECKS")
    print(f"  YouTube regression (lost > 0): {'YES ⚠' if regression_youtube else 'NO ✓'}")
    print(f"  Reddit regression  (lost > 0): {'YES ⚠' if regression_reddit else 'NO ✓'}")
    print(f"  Safe to enable:               {'YES ✓' if safe_to_enable else 'NO — DO NOT ENABLE'}")

    if total_changed > 0 and changed_examples:
        print(f"\n  TOP {min(top_n, len(changed_examples))} CHANGED MATCHES")
        for i, ex in enumerate(changed_examples[:top_n], 1):
            print(f"\n  [{i}] {ex['platform']} id={ex['id']}")
            if ex.get("title"):
                print(f"      title:  {ex['title']}")
            if ex.get("text_snippet"):
                print(f"      text:   {ex['text_snippet']}")
            if ex["gained"]:
                print(f"      GAINED: {ex['gained']}")
            if ex["lost"]:
                print(f"      LOST:   {ex['lost']}")
            for d in ex["new_details"]:
                print(
                    f"      → {d['canonical_name']}  field={d['matched_field']}"
                    f"  conf={d['final_confidence']}"
                )

    if false_positive_risk:
        print(f"\n  FALSE-POSITIVE RISK EXAMPLES (new matches, low conf, weak field)")
        for i, fp in enumerate(false_positive_risk[:top_n], 1):
            print(
                f"  [{i}] {fp['platform']}  entity={fp['entity']}"
                f"  field={fp['matched_field']}  conf={fp['final_confidence']}"
            )
            if fp.get("title"):
                print(f"       title: {fp['title']}")

    print("\n" + "=" * 68)

    summary = {
        "run_at": datetime.utcnow().isoformat(),
        "start_date": start_date,
        "end_date": end_date,
        "platform_filter": platform,
        "items_total": total,
        "old_resolved": old_total,
        "new_resolved": new_total,
        "items_gained": total_gained,
        "items_lost": total_lost,
        "items_changed": total_changed,
        "regression_youtube": regression_youtube,
        "regression_reddit": regression_reddit,
        "safe_to_enable": safe_to_enable,
        "per_platform": dict(stats),
        "gain_examples": gain_examples[:top_n],
        "changed_examples": changed_examples[:top_n],
        "false_positive_risk": false_positive_risk[:top_n],
    }

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SC1.3 multi-field resolver replay/backtest"
    )
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--platform", default=None,
                        help="Filter to one platform (youtube, reddit, tiktok)")
    parser.add_argument("--limit", type=int, default=2000,
                        help="Max items to replay (default 2000)")
    parser.add_argument("--top-n", type=int, default=20,
                        help="Max changed/risk examples to show (default 20)")
    parser.add_argument("--output-dir", default="outputs",
                        help="Directory for JSON summary (default: outputs/)")
    args = parser.parse_args()

    summary = run_replay(
        start_date=args.start,
        end_date=args.end,
        platform=args.platform,
        limit=args.limit,
        top_n=args.top_n,
    )

    if summary:
        os.makedirs(args.output_dir, exist_ok=True)
        fname = f"{args.output_dir}/replay_mf_resolver_{args.start}_{args.end}.json"
        with open(fname, "w") as fh:
            json.dump(summary, fh, indent=2, default=str)
        print(f"\n[replay] JSON summary written to: {fname}")


if __name__ == "__main__":
    main()
