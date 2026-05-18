"""SIG-ID1 — Amber Elixir Cross-Brand Attribution Repair.

Production evidence (2026-05-18):
    YouTube video FcgstioOvp8 ("These 12 Colognes Are Game Changers For Warm Weather: Week #329")
    description begins: "Vertus Amber Elixir"
    Resolver matched bare alias "amber elixir" → Oriflame Amber Elixir (entity_id: 7b30ea83-...)
    Root cause: Vertus Amber Elixir absent from resolver catalog; "amber elixir" bare alias
    points only to Oriflame (G3-A Tier B, seeded when Oriflame was the only catalog match).

    Result: 2 entity_mentions for Oriflame Amber Elixir from Vertus-sourced content,
    1 ts row with mentions > 0, 8 total ts rows (carry-forward), score=41.1.

Repair:
    Part 1: Strip "Amber Elixir" (Oriflame) from RS rows sourced from Vertus content.
    Part 2: Delete entity_mentions for Oriflame Amber Elixir (all 2 false attributions).
    Part 3: Delete entity_timeseries_daily for Oriflame Amber Elixir (8 rows).
    Part 4: Delete signals for Oriflame Amber Elixir if any exist.
    Part 5: Delete signal_intelligence_snapshots for Oriflame Amber Elixir if any.

OPS-PV1 Repair Scope Compatibility Rule: full-history RS strip, no --days window.
OPS-EE1: targeted direct-DB repair — no broad aggregation recompute needed (2 mentions).

Guard coverage: "amber elixir" added to _AMBIGUOUS_PHRASE_GUARD in SIG-ID1 requiring
{"oriflame"} brand proximity — future Oriflame Amber Elixir content still resolves
correctly when "oriflame" appears nearby.

Usage:
    python3 scripts/sig_id1_amber_elixir_repair.py            # dry-run (default)
    python3 scripts/sig_id1_amber_elixir_repair.py --apply    # apply to production
"""

from __future__ import annotations

import argparse
import json
import sys

import psycopg2

ORIFLAME_AMBER_ELIXIR_ID = "7b30ea83-2e58-4b44-8f23-d30b0c4a6b39"  # from production audit
CANONICAL_NAME = "Amber Elixir"
BRAND_NAME = "Oriflame"


def main() -> None:
    parser = argparse.ArgumentParser(description="SIG-ID1 Amber Elixir repair")
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

    print(f"=== SIG-ID1 Amber Elixir Repair {'APPLY' if apply else 'DRY-RUN'} ===\n")

    # Confirm entity_id from entity_market
    cur.execute(
        "SELECT id, canonical_name, brand_name FROM entity_market "
        "WHERE canonical_name = %s AND brand_name = %s AND entity_type = 'perfume'",
        (CANONICAL_NAME, BRAND_NAME),
    )
    row = cur.fetchone()
    if not row:
        print(f"ERROR: Could not find entity_market row for '{CANONICAL_NAME}' / '{BRAND_NAME}'")
        sys.exit(1)
    entity_id = str(row[0])
    print(f"Entity confirmed: id={entity_id[:8]}... | {row[2]} | {row[1]}")

    # ------------------------------------------------------------------
    # Part 1 — Full-history RS strip
    # ------------------------------------------------------------------
    print("\n=== Part 1: RS strip (full history) ===")
    cur.execute(
        "SELECT COUNT(*) FROM resolved_signals WHERE resolved_entities_json LIKE %s",
        (f"%{CANONICAL_NAME}%",),
    )
    rs_text_matches = cur.fetchone()[0]

    cur.execute(
        "SELECT id, resolved_entities_json FROM resolved_signals "
        "WHERE resolved_entities_json LIKE %s",
        (f"%{CANONICAL_NAME}%",),
    )
    rs_rows = cur.fetchall()

    rs_updated = 0
    for rs_id, rs_json in rs_rows:
        try:
            entities = json.loads(rs_json)
        except (json.JSONDecodeError, TypeError):
            continue
        filtered = [e for e in entities if e.get("canonical_name") != CANONICAL_NAME]
        if len(filtered) == len(entities):
            continue
        new_json = json.dumps(filtered) if filtered else "[]"
        if apply:
            cur.execute(
                "UPDATE resolved_signals SET resolved_entities_json = %s WHERE id = %s",
                (new_json, rs_id),
            )
        rs_updated += 1

    print(f"  RS text matches: {rs_text_matches}, rows to update: {rs_updated}")

    # RS residual verification
    cur.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT rs.id FROM resolved_signals rs
            WHERE rs.resolved_entities_json LIKE %s
              AND EXISTS (
                SELECT 1 FROM jsonb_array_elements(rs.resolved_entities_json::jsonb) elem
                WHERE elem->>'canonical_name' = %s
              )
        ) sub
        """,
        (f"%{CANONICAL_NAME}%", CANONICAL_NAME),
    )
    residual = cur.fetchone()[0]
    print(f"  RS residual (exact jsonb check): {residual} {'[OK if 0]' if residual == 0 else '[FAIL — check manually]'}")

    # ------------------------------------------------------------------
    # Part 2 — entity_mentions
    # ------------------------------------------------------------------
    print("\n=== Part 2: entity_mentions cleanup ===")
    cur.execute(
        "SELECT COUNT(*) FROM entity_mentions WHERE entity_id = %s",
        (entity_id,),
    )
    em_count = cur.fetchone()[0]
    print(f"  entity_mentions: {em_count}")
    if apply and em_count > 0:
        cur.execute("DELETE FROM entity_mentions WHERE entity_id = %s", (entity_id,))

    # ------------------------------------------------------------------
    # Part 3 — entity_timeseries_daily
    # ------------------------------------------------------------------
    print("\n=== Part 3: entity_timeseries_daily cleanup ===")
    cur.execute(
        "SELECT COUNT(*) FROM entity_timeseries_daily WHERE entity_id = %s",
        (entity_id,),
    )
    ts_count = cur.fetchone()[0]
    print(f"  entity_timeseries_daily: {ts_count}")
    if apply and ts_count > 0:
        cur.execute("DELETE FROM entity_timeseries_daily WHERE entity_id = %s", (entity_id,))

    # ------------------------------------------------------------------
    # Part 4 — signals
    # ------------------------------------------------------------------
    print("\n=== Part 4: signals cleanup ===")
    cur.execute(
        "SELECT COUNT(*) FROM signals WHERE entity_id = %s",
        (entity_id,),
    )
    sig_count = cur.fetchone()[0]
    print(f"  signals: {sig_count}")
    if apply and sig_count > 0:
        cur.execute("DELETE FROM signals WHERE entity_id = %s", (entity_id,))

    # ------------------------------------------------------------------
    # Part 5 — signal_intelligence_snapshots
    # ------------------------------------------------------------------
    print("\n=== Part 5: signal_intelligence_snapshots cleanup ===")
    cur.execute(
        "SELECT COUNT(*) FROM signal_intelligence_snapshots WHERE entity_id = %s::uuid",
        (entity_id,),
    )
    snap_count = cur.fetchone()[0]
    print(f"  signal_intelligence_snapshots: {snap_count}")
    if apply and snap_count > 0:
        cur.execute(
            "DELETE FROM signal_intelligence_snapshots WHERE entity_id = %s::uuid",
            (entity_id,),
        )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\n=== Summary ===")
    print(f"  RS rows stripped: {rs_updated}")
    print(f"  entity_mentions to delete: {em_count}")
    print(f"  ts rows to delete: {ts_count}")
    print(f"  signals to delete: {sig_count}")
    print(f"  snapshots to delete: {snap_count}")

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
