"""SIG-QA1-REPAIR — Source-Evidence Pollution Cleanup for 5 Confirmed Unsupported Entities.

Approved repair targets (entity_id, canonical_name, brand):
  c08867ea — Pure Luxury           — Wolken Parfums   — Type D
  d22eea5f — On the Rocks          — Wolken Parfums   — Type F
  411ebef2 — Enjoy the Day         — Wolken Parfums   — Type D
  7277f176 — Orange Blossom        — Angela Flanders  — Type B
  0c5f5215 — Cire Trudon Revolution — Cire Trudon     — Type C

OPS-PV1 Repair Scope Compatibility Rule: full-history RS strip (no --days window).
OPS-EE1: targeted direct-DB repair — no broad aggregation recompute.

Brand rollup strategy:
  Wolken Parfums   → delete ALL brand ts/signals (no other tracked perfumes)
  Angela Flanders  → delete ALL brand ts/signals, recompute from Precious One (entity_id 03ab1d60)
  Cire Trudon      → delete ALL brand ts/signals (no other tracked perfumes)

Usage:
  python3 scripts/sig_qa1_repair.py            # dry-run (default)
  python3 scripts/sig_qa1_repair.py --apply    # apply to production
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import psycopg2


# ---------------------------------------------------------------------------
# Approved repair targets
# ---------------------------------------------------------------------------

PERFUME_TARGETS = [
    {"entity_id": "c08867ea-aaa2-4876-9660-c63bad62e823", "canonical_name": "Pure Luxury",           "brand": "Wolken Parfums"},
    {"entity_id": "d22eea5f-c2e4-407c-99bd-7d8a3a058f97", "canonical_name": "On the Rocks",          "brand": "Wolken Parfums"},
    {"entity_id": "411ebef2-6d86-44e5-bbd9-d0ebca5422fc", "canonical_name": "Enjoy the Day",         "brand": "Wolken Parfums"},
    {"entity_id": "7277f176-d8df-4e24-b24b-63372cfa39a3", "canonical_name": "Orange Blossom",        "brand": "Angela Flanders"},
    # Cire Trudon Revolution: entity_market stores "Cire Trudon Revolution" (suffix-stripped by _base_name()),
    # but resolved_signals stores the resolver canonical_name "Cire Trudon Revolution Eau de Parfum".
    # Both names must be stripped from RS.
    {"entity_id": "0c5f5215-2381-4d91-85e9-4ee06f4af236", "canonical_name": "Cire Trudon Revolution", "brand": "Cire Trudon",
     "rs_canonical_names": ["Cire Trudon Revolution", "Cire Trudon Revolution Eau de Parfum"]},
]

BRAND_ENTITIES = {
    "Wolken Parfums":  "63109530-21a2-41d3-a27b-59e0adaf4f2d",
    "Angela Flanders": "a7cf33b5-9506-4936-8e03-ad336f08c6f7",
    "Cire Trudon":     "7c10adf5-98bf-4d4e-a93a-175258577808",
}

# Angela Flanders' only other tracked perfume — used for brand recompute
PRECIOUS_ONE_ID = "03ab1d60-332d-4dfe-8833-d0695a4abfb0"


# ---------------------------------------------------------------------------
# RS strip helpers
# ---------------------------------------------------------------------------

def _strip_rs_for_entity(cur: Any, canonical_name: str, apply: bool) -> dict:
    """Remove canonical_name from resolved_entities_json for all RS rows."""
    cur.execute(
        "SELECT COUNT(*) FROM resolved_signals WHERE resolved_entities_json LIKE %s",
        (f"%{canonical_name}%",),
    )
    text_match_count = cur.fetchone()[0]

    cur.execute(
        """
        SELECT id, resolved_entities_json
        FROM resolved_signals
        WHERE resolved_entities_json LIKE %s
        """,
        (f"%{canonical_name}%",),
    )
    rows = cur.fetchall()

    updated = 0
    for rs_id, rs_json in rows:
        try:
            entities = json.loads(rs_json)
        except (json.JSONDecodeError, TypeError):
            continue
        original_len = len(entities)
        filtered = [e for e in entities if e.get("canonical_name") != canonical_name]
        if len(filtered) == original_len:
            continue  # no change — text match was a substring of another entity name

        new_json = json.dumps(filtered)
        if apply:
            cur.execute(
                "UPDATE resolved_signals SET resolved_entities_json = %s WHERE id = %s",
                (new_json, rs_id),
            )
        updated += 1

    return {"text_matches": text_match_count, "rows_updated": updated}


def _verify_rs_residual(cur: Any, canonical_name: str) -> int:
    """Count exact canonical_name matches remaining in resolved_signals."""
    cur.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT rs.id
            FROM resolved_signals rs
            WHERE rs.resolved_entities_json LIKE %s
              AND EXISTS (
                SELECT 1
                FROM jsonb_array_elements(rs.resolved_entities_json::jsonb) elem
                WHERE elem->>'canonical_name' = %s
              )
        ) sub
        """,
        (f"%{canonical_name}%", canonical_name),
    )
    return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# Downstream cleanup helpers
# ---------------------------------------------------------------------------

def _count_and_delete(cur: Any, table: str, entity_id: str, apply: bool) -> int:
    if table == "signal_intelligence_snapshots":
        cur.execute(f"SELECT COUNT(*) FROM {table} WHERE entity_id = %s::uuid", (entity_id,))
    else:
        cur.execute(f"SELECT COUNT(*) FROM {table} WHERE entity_id = %s", (entity_id,))
    count = cur.fetchone()[0]
    if apply and count > 0:
        if table == "signal_intelligence_snapshots":
            cur.execute(f"DELETE FROM {table} WHERE entity_id = %s::uuid", (entity_id,))
        else:
            cur.execute(f"DELETE FROM {table} WHERE entity_id = %s", (entity_id,))
    return count


# ---------------------------------------------------------------------------
# Angela Flanders brand recompute
# ---------------------------------------------------------------------------

def _recompute_angela_flanders_brand(cur: Any, brand_id: str, apply: bool) -> dict:
    """
    Recompute Angela Flanders brand ts from Precious One entity_timeseries_daily.
    Only creates rows where Precious One mention_count > 0 (matching HAVING SUM > 0 in rollup).
    OPS-EE1: direct SQL INSERT — no full pipeline recompute needed (only 1 real mention date).
    """
    # Get Precious One ts rows where mention_count > 0
    cur.execute(
        """
        SELECT date, mention_count, engagement_sum, unique_authors,
               composite_market_score, growth_rate, momentum, acceleration,
               volatility, confidence_avg, trend_state, score_formula_version
        FROM entity_timeseries_daily
        WHERE entity_id = %s AND mention_count > 0
        ORDER BY date
        """,
        (PRECIOUS_ONE_ID,),
    )
    source_rows = cur.fetchall()

    if not source_rows:
        return {"recomputed_rows": 0, "note": "No Precious One mention_count > 0 rows found"}

    inserted = 0
    for row in source_rows:
        (dt, mentions, engagement, authors, score, growth, momentum,
         accel, volatility, conf_avg, trend_state, formula_ver) = row

        if apply:
            cur.execute(
                """
                INSERT INTO entity_timeseries_daily (
                    entity_id, entity_type, date,
                    mention_count, engagement_sum, unique_authors,
                    composite_market_score, growth_rate, momentum, acceleration,
                    volatility, confidence_avg, trend_state, score_formula_version,
                    weighted_signal_score
                ) VALUES (%s, 'brand', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    brand_id, dt, mentions, engagement, authors,
                    score, growth, momentum, accel, volatility,
                    conf_avg, trend_state, formula_ver, score,
                ),
            )
        inserted += 1

    return {"recomputed_rows": inserted, "dates": [str(r[0]) for r in source_rows]}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="SIG-QA1-REPAIR targeted cleanup")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: dry-run)")
    args = parser.parse_args()
    apply = args.apply

    import os
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    cur = conn.cursor()

    print(f"=== SIG-QA1-REPAIR {'APPLY' if apply else 'DRY-RUN'} ===\n")

    # ------------------------------------------------------------------
    # Part 2 — Full-history RS strip
    # ------------------------------------------------------------------
    print("=== Part 2: Full-history RS strip ===")
    rs_results = {}
    for t in PERFUME_TARGETS:
        names_to_strip = t.get("rs_canonical_names", [t["canonical_name"]])
        total_matches = 0
        total_updated = 0
        for cn in names_to_strip:
            result = _strip_rs_for_entity(cur, cn, apply)
            total_matches += result["text_matches"]
            total_updated += result["rows_updated"]
        rs_results[t["canonical_name"]] = {"text_matches": total_matches, "rows_updated": total_updated}
        print(f"  [{t['canonical_name']}] text_matches={total_matches}, rows_updated={total_updated}")
    print()

    # ------------------------------------------------------------------
    # Part 3 — Downstream perfume entity cleanup
    # ------------------------------------------------------------------
    print("=== Part 3: Downstream perfume entity cleanup ===")
    downstream_results = {}
    tables = ["entity_mentions", "entity_timeseries_daily", "signals", "signal_intelligence_snapshots"]
    for t in PERFUME_TARGETS:
        counts = {}
        for table in tables:
            counts[table] = _count_and_delete(cur, table, t["entity_id"], apply)
        downstream_results[t["canonical_name"]] = counts
        print(f"  [{t['canonical_name']}] mentions={counts['entity_mentions']}, "
              f"ts={counts['entity_timeseries_daily']}, "
              f"signals={counts['signals']}, "
              f"snapshots={counts['signal_intelligence_snapshots']}")
    print()

    # ------------------------------------------------------------------
    # Part 4 — Brand rollup repair
    # ------------------------------------------------------------------
    print("=== Part 4: Brand rollup repair ===")

    for brand_name, brand_id in BRAND_ENTITIES.items():
        cur.execute("SELECT COUNT(*) FROM entity_timeseries_daily WHERE entity_id = %s", (brand_id,))
        brand_ts = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM signals WHERE entity_id = %s", (brand_id,))
        brand_sigs = cur.fetchone()[0]

        if apply:
            cur.execute("DELETE FROM entity_timeseries_daily WHERE entity_id = %s", (brand_id,))
            cur.execute("DELETE FROM signals WHERE entity_id = %s", (brand_id,))

        print(f"  [{brand_name}] deleted ts={brand_ts}, signals={brand_sigs}")

    # Angela Flanders: recompute from Precious One
    af_brand_id = BRAND_ENTITIES["Angela Flanders"]
    recompute = _recompute_angela_flanders_brand(cur, af_brand_id, apply)
    print(f"  [Angela Flanders] brand recompute: rows_inserted={recompute['recomputed_rows']}, dates={recompute.get('dates', [])}")
    print()

    # ------------------------------------------------------------------
    # RS residual verification
    # ------------------------------------------------------------------
    print("=== Verification: RS residual exact matches ===")
    all_clean = True
    for t in PERFUME_TARGETS:
        names_to_verify = t.get("rs_canonical_names", [t["canonical_name"]])
        total_residual = 0
        for cn in names_to_verify:
            total_residual += _verify_rs_residual(cur, cn)
        status = "OK" if total_residual == 0 else "FAIL"
        if total_residual != 0:
            all_clean = False
        print(f"  [{t['canonical_name']}] residual={total_residual} [{status}]")

    print()
    if all_clean:
        print("RS verification: ALL CLEAN")
    else:
        print("RS verification: FAILURES DETECTED — do not commit")

    if apply:
        conn.commit()
        print("\nCommitted to production.")
    else:
        conn.rollback()
        print("\nDry-run — no changes committed.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
