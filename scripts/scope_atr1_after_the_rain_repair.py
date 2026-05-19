"""SCOPE-ATR1 — After the Rain (Declaration Grooming) out-of-scope repair.

Scope decision: Declaration Grooming "After the Rain" is a shaving soap + aftershave splash
(non-perfume grooming scent). Company went EOB 2026-01-31. No EDP/cologne/perfume product.
All RS rows are likely about Solstice Scents "After the Rain" EDP — wrong identity attribution.

entity_id:       cff58833-d117-42be-bf4a-263350df79f3  (After the Rain, Declaration Grooming)
brand entity_id: 3690344f-...  (Declaration Grooming / L&L Grooming)

Full-history RS strip per OPS-PV1 Repair Scope Compatibility Rule (no --days window).

Usage:
    python3 scripts/scope_atr1_after_the_rain_repair.py             # dry-run
    python3 scripts/scope_atr1_after_the_rain_repair.py --apply     # execute
"""

import os
import sys
import argparse
import psycopg2

PERFUME_CANONICAL = "After the Rain"
BRAND_CANONICAL = "Declaration Grooming"
PERFUME_ENTITY_ID = "cff58833-d117-42be-bf4a-263350df79f3"

def _get_brand_entity_id(cur):
    cur.execute(
        "SELECT id FROM entity_market "
        "WHERE entity_type = 'brand' "
        "  AND (brand_name ILIKE '%declaration%grooming%' OR brand_name ILIKE '%l&l grooming%') "
        "LIMIT 1"
    )
    row = cur.fetchone()
    return str(row[0]) if row else None


def run(apply: bool):
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    cur = conn.cursor()
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[scope-atr1-repair] {mode}")
    print(f"  Perfume entity: {PERFUME_CANONICAL} (id={PERFUME_ENTITY_ID})")

    # -- Brand entity lookup
    brand_entity_id = _get_brand_entity_id(cur)
    if brand_entity_id:
        print(f"  Brand entity: {BRAND_CANONICAL} (id={brand_entity_id})")
    else:
        print(f"  Brand entity: NOT FOUND (may already be absent)")

    # -- RS strip: full-history (no date window per OPS-PV1 rule)
    cur.execute("""
        SELECT COUNT(*) FROM resolved_signals
        WHERE resolved_entities_json::jsonb @> jsonb_build_array(
            jsonb_build_object('canonical_name', %s)
        )
    """, (PERFUME_CANONICAL,))
    rs_count = cur.fetchone()[0]
    print(f"\n  RS rows containing '{PERFUME_CANONICAL}': {rs_count}")

    if apply:
        cur.execute("""
            UPDATE resolved_signals
            SET resolved_entities_json = (
                SELECT jsonb_agg(elem)
                FROM jsonb_array_elements(COALESCE(resolved_entities_json::jsonb, '[]'::jsonb)) AS elem
                WHERE elem->>'canonical_name' != %s
            )::text
            WHERE resolved_entities_json::jsonb @> jsonb_build_array(
                jsonb_build_object('canonical_name', %s)
            )
        """, (PERFUME_CANONICAL, PERFUME_CANONICAL))
        rs_updated = cur.rowcount
        print(f"    -> stripped from {rs_updated} RS rows")

    # -- Downstream cleanup for perfume entity
    for table, label in [
        ("entity_mentions", "entity_mentions"),
        ("entity_timeseries_daily", "ts"),
        ("signals", "signals"),
        ("signal_intelligence_snapshots", "snaps"),
    ]:
        cur.execute(f"SELECT COUNT(*) FROM {table} WHERE entity_id = %s", (PERFUME_ENTITY_ID,))
        cnt = cur.fetchone()[0]
        print(f"  {label} (perfume): {cnt}")
        if apply and cnt > 0:
            cur.execute(f"DELETE FROM {table} WHERE entity_id = %s", (PERFUME_ENTITY_ID,))
            print(f"    -> deleted {cur.rowcount}")

    # -- Brand entity cleanup (Declaration Grooming — no other tracked perfumes)
    if brand_entity_id:
        cur.execute(
            "SELECT COUNT(*) FROM entity_market "
            "WHERE entity_type = 'perfume' "
            "  AND brand_name ILIKE '%%declaration%%' "
            "  AND id != %s",
            (PERFUME_ENTITY_ID,)
        )
        other_tracked = cur.fetchone()[0]
        print(f"\n  Other tracked perfumes under Declaration Grooming: {other_tracked}")

        for table, label in [
            ("entity_timeseries_daily", "brand ts"),
            ("signals", "brand signals"),
        ]:
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE entity_id = %s", (brand_entity_id,))
            cnt = cur.fetchone()[0]
            print(f"  {label}: {cnt}")
            if apply and cnt > 0:
                cur.execute(f"DELETE FROM {table} WHERE entity_id = %s", (brand_entity_id,))
                print(f"    -> deleted {cur.rowcount}")

    if apply:
        conn.commit()
        print("\nSCOPE-ATR1 repair committed.")
    else:
        conn.rollback()
        print("\nDry-run complete — set --apply to execute.")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Execute repair (default: dry-run)")
    args = parser.parse_args()
    run(args.apply)
