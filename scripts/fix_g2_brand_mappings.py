#!/usr/bin/env python3
"""
scripts/fix_g2_brand_mappings.py — G2 Brand Mapping Remediation

Root cause:
  _upsert_brand_and_perfume_catalog_first used a last-word-split heuristic to
  derive brand names for entities not yet in the market `perfumes` table.
  G2-seeded entities (present only in resolver_perfumes) triggered this path,
  producing truncated phantom brand names.

Affected entities:
  - Armaf Club de Nuit          → stored brand "Armaf Club de"        (correct: "Armaf")
  - Armaf Club de Nuit Intense Man → "Armaf Club de Nuit Intense"     (correct: "Armaf")
  - Al Haramain Amber Oud       → "Al Haramain Amber"                 (correct: "Al Haramain")
  - Paco Rabanne 1 Million      → "Paco Rabanne 1"                    (correct: "Paco Rabanne")
  - Yves Saint Laurent Black Opium → "Yves Saint Laurent Black"       (correct: "Yves Saint Laurent")

This script, in --apply mode, performs the following in FK order:
  1. Find or create correct market brand rows (brands table).
  2. Update perfumes.brand_id to point to correct brands.
  3. Update entity_market.brand_name for affected perfume rows.
  4. Delete signals under 5 phantom brand entity_market UUIDs.
  5. Delete entity_timeseries_daily rows under phantom brand entity_market UUIDs.
  6. Delete 5 phantom brand entity_market rows.
  7. Delete 5 phantom market brand rows.

After --apply, re-run aggregation + signal detection for affected dates.

Default mode: DRY-RUN (read-only, zero writes).
Use --apply to write.

Idempotent: safe to re-run. All writes use ON CONFLICT / upsert patterns
or check existence before acting.

Rollback: no schema changes made — all writes are data-level. To revert:
  - Restore from a pre-apply DB snapshot.
  - Or restore the 5 brand rows + 5 perfume brand_id links manually.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

logging.basicConfig(
    format="%(asctime)s %(levelname)-7s %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Perfume canonical name → correct brand name (from resolver_fragrance_master)
AFFECTED_PERFUMES: dict[str, str] = {
    "Armaf Club de Nuit":             "Armaf",
    "Armaf Club de Nuit Intense Man": "Armaf",
    "Al Haramain Amber Oud":          "Al Haramain",
    "Paco Rabanne 1 Million":         "Paco Rabanne",
    "Yves Saint Laurent Black Opium": "Yves Saint Laurent",
}

# Phantom brand names created by the heuristic (to be deleted)
PHANTOM_BRAND_NAMES: list[str] = [
    "Armaf Club de",
    "Armaf Club de Nuit Intense",
    "Al Haramain Amber",
    "Paco Rabanne 1",
    "Yves Saint Laurent Black",
]

# Phantom brand entity_market entity_ids created by the brand rollup
PHANTOM_BRAND_SLUGS: list[str] = [
    "brand-armaf-club-de",
    "brand-armaf-club-de-nuit-intense",
    "brand-al-haramain-amber",
    "brand-paco-rabanne-1",
    "brand-yves-saint-laurent-black",
]

# Dates that need aggregation + signal detection re-run after apply.
# Derived from: dates with real perfume timeseries mentions + phantom brand timeseries.
RERUN_DATES: list[str] = [
    "2026-04-09",
    "2026-04-11",
    "2026-04-15",
    "2026-04-16",
    "2026-04-17",
    "2026-04-18",
    "2026-04-19",
    "2026-04-20",
    "2026-04-22",
    "2026-04-23",
    "2026-04-24",
    "2026-04-25",
]


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------

def _get_conn():
    import psycopg2
    url = os.environ.get("DATABASE_URL")
    if not url:
        log.error("DATABASE_URL not set")
        sys.exit(1)
    if url.startswith("postgresql+psycopg2://"):
        url = url.replace("postgresql+psycopg2://", "postgresql://", 1)
    log.info("Connecting to Postgres …")
    return psycopg2.connect(url)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
    import re
    slug = re.sub(r"[^\w\s-]", "", name.lower().strip())
    return re.sub(r"[\s_]+", "-", slug).strip("-")


def _generate_ticker(name: str) -> str:
    """Minimal ticker generator matching the aggregator's logic."""
    import re
    words = re.sub(r"[^a-zA-Z0-9\s]", "", name).upper().split()
    if not words:
        return "UNKN"
    if len(words) == 1:
        return words[0][:5]
    return "".join(w[0] for w in words)[:5]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(apply: bool) -> None:
    conn = _get_conn()
    cur = conn.cursor()

    sep = "=" * 70
    print()
    print(sep)
    print(f"G2 Brand Mapping Remediation — {'** DRY RUN ** (no writes)' if not apply else 'APPLYING'}")
    print(sep)

    # ── 1. Locate affected perfume rows ─────────────────────────────────────
    print("\n[1] Affected market perfumes table rows")
    perfume_rows: dict[str, dict] = {}  # canonical_name → row info
    for canonical_name in AFFECTED_PERFUMES:
        cur.execute(
            "SELECT p.id, p.brand_id, b.name AS current_brand "
            "FROM perfumes p "
            "JOIN brands b ON b.id = p.brand_id "
            "WHERE p.name = %s LIMIT 1",
            (canonical_name,),
        )
        row = cur.fetchone()
        if row:
            perfume_rows[canonical_name] = {
                "perfume_id": row[0],
                "current_brand_id": row[1],
                "current_brand": row[2],
                "correct_brand": AFFECTED_PERFUMES[canonical_name],
            }
            print(f"  {canonical_name!r}")
            print(f"    perfume_id      : {row[0]}")
            print(f"    current brand   : {row[2]!r}")
            print(f"    correct brand   : {AFFECTED_PERFUMES[canonical_name]!r}")
        else:
            print(f"  {canonical_name!r} — NOT FOUND in market perfumes (unexpected)")

    # ── 2. Find / prepare correct brand rows ────────────────────────────────
    print("\n[2] Correct market brand rows")
    correct_brand_ids: dict[str, str] = {}  # brand_name → UUID

    unique_correct_brands = sorted(set(AFFECTED_PERFUMES.values()))
    for brand_name in unique_correct_brands:
        slug = _slugify(brand_name)
        cur.execute("SELECT id, name FROM brands WHERE slug = %s LIMIT 1", (slug,))
        row = cur.fetchone()
        if row:
            correct_brand_ids[brand_name] = row[0]
            print(f"  {brand_name!r} → EXISTS (id={row[0]})")
        else:
            ticker = _generate_ticker(brand_name)
            # Check ticker collision
            cur.execute("SELECT 1 FROM brands WHERE ticker = %s LIMIT 1", (ticker,))
            if cur.fetchone():
                ticker = ticker[:4] + "X"
            print(f"  {brand_name!r} → MISSING — would create (slug={slug!r}, ticker={ticker!r})")
            correct_brand_ids[brand_name] = None  # will be assigned after create

    # ── 3. Phantom brand entity_market rows ─────────────────────────────────
    print("\n[3] Phantom brand entity_market rows to delete")
    cur.execute(
        "SELECT id::text, entity_id, canonical_name FROM entity_market "
        "WHERE entity_type = 'brand' AND entity_id = ANY(%s)",
        (PHANTOM_BRAND_SLUGS,),
    )
    phantom_em_rows = cur.fetchall()
    phantom_em_uuids = [r[0] for r in phantom_em_rows]
    for r in phantom_em_rows:
        print(f"  entity_id={r[1]!r}, canonical_name={r[2]!r}, uuid={r[0]}")
    if not phantom_em_rows:
        print("  (none found — already cleaned?)")

    # ── 4. Phantom brand timeseries rows ────────────────────────────────────
    print("\n[4] Phantom brand timeseries rows to delete")
    ts_count = 0
    if phantom_em_uuids:
        cur.execute(
            "SELECT etd.entity_id::text, e.canonical_name, etd.date, etd.mention_count "
            "FROM entity_timeseries_daily etd "
            "JOIN entity_market e ON e.id = etd.entity_id "
            "WHERE etd.entity_id::text = ANY(%s) "
            "ORDER BY e.canonical_name, etd.date",
            (phantom_em_uuids,),
        )
        ts_rows = cur.fetchall()
        ts_count = len(ts_rows)
        for r in ts_rows:
            print(f"  brand={r[1]!r}  date={r[2]}  mentions={r[3]:.1f}")
    print(f"  Total: {ts_count} rows to delete")

    # ── 5. Phantom brand signal rows ─────────────────────────────────────────
    print("\n[5] Phantom brand signal rows to delete")
    sig_count = 0
    if phantom_em_uuids:
        cur.execute(
            "SELECT s.entity_id::text, e.canonical_name, s.signal_type, s.detected_at::date "
            "FROM signals s "
            "JOIN entity_market e ON e.id = s.entity_id "
            "WHERE s.entity_id::text = ANY(%s) "
            "ORDER BY e.canonical_name, s.detected_at",
            (phantom_em_uuids,),
        )
        sig_rows = cur.fetchall()
        sig_count = len(sig_rows)
        for r in sig_rows:
            print(f"  brand={r[1]!r}  signal={r[2]!r}  date={r[3]}")
    print(f"  Total: {sig_count} rows to delete")

    # ── 6. Phantom market brand rows ─────────────────────────────────────────
    print("\n[6] Phantom market brand rows to delete")
    cur.execute(
        "SELECT id, name, slug FROM brands WHERE name = ANY(%s)",
        (PHANTOM_BRAND_NAMES,),
    )
    phantom_brand_rows = cur.fetchall()
    phantom_brand_ids = [r[0] for r in phantom_brand_rows]
    for r in phantom_brand_rows:
        print(f"  id={r[0]}  name={r[1]!r}  slug={r[2]!r}")
    if not phantom_brand_rows:
        print("  (none found — already cleaned?)")

    # ── 7. entity_market brand_name updates ──────────────────────────────────
    print("\n[7] entity_market perfume brand_name updates")
    for canonical_name, correct_brand in AFFECTED_PERFUMES.items():
        cur.execute(
            "SELECT brand_name FROM entity_market "
            "WHERE canonical_name = %s AND entity_type = 'perfume' LIMIT 1",
            (canonical_name,),
        )
        row = cur.fetchone()
        if row:
            print(f"  {canonical_name!r}: {row[0]!r} → {correct_brand!r}")
        else:
            print(f"  {canonical_name!r}: NOT FOUND in entity_market")

    # ── Summary ──────────────────────────────────────────────────────────────
    print()
    print(sep)
    print("Dry-run summary" if not apply else "Apply summary")
    print(sep)
    missing_brands = [b for b, uid in correct_brand_ids.items() if uid is None]
    print(f"  Correct brands to CREATE    : {len(missing_brands)} {missing_brands}")
    print(f"  Perfumes to re-link         : {len(perfume_rows)}")
    print(f"  entity_market brand updates : {len(AFFECTED_PERFUMES)}")
    print(f"  Phantom brand EM rows       : {len(phantom_em_rows)}")
    print(f"  Phantom timeseries rows     : {ts_count}")
    print(f"  Phantom signal rows         : {sig_count}")
    print(f"  Phantom market brand rows   : {len(phantom_brand_rows)}")
    print(f"  DB writes                   : {'NO (dry-run)' if not apply else 'YES'}")
    print(sep)

    if not apply:
        print()
        print("Dry-run complete — zero DB writes performed.")
        print()
        print("Apply command:")
        print("  DATABASE_URL=<prod-url> python3 scripts/fix_g2_brand_mappings.py --apply")
        print()
        print("After --apply, re-run aggregation + signals for each affected date:")
        for d in RERUN_DATES:
            print(f"  DATABASE_URL=<prod-url> python3 -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics --date {d}")
        print()
        for d in RERUN_DATES:
            print(f"  DATABASE_URL=<prod-url> python3 -m perfume_trend_sdk.jobs.detect_breakout_signals --date {d}")
        conn.close()
        return

    # ── APPLY ────────────────────────────────────────────────────────────────

    # Step A: create missing correct brand rows
    for brand_name in unique_correct_brands:
        if correct_brand_ids[brand_name] is not None:
            continue
        slug = _slugify(brand_name)
        ticker = _generate_ticker(brand_name)
        cur.execute("SELECT 1 FROM brands WHERE ticker = %s LIMIT 1", (ticker,))
        if cur.fetchone():
            ticker = ticker[:4] + "X"
        cur.execute(
            "INSERT INTO brands (name, slug, ticker, created_at) "
            "VALUES (%s, %s, %s, NOW()) "
            "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name "
            "RETURNING id",
            (brand_name, slug, ticker),
        )
        new_id = cur.fetchone()[0]
        correct_brand_ids[brand_name] = new_id
        log.info("Created brand %r id=%s", brand_name, new_id)

    # Step B: update perfumes.brand_id
    for canonical_name, correct_brand in AFFECTED_PERFUMES.items():
        brand_id = correct_brand_ids[correct_brand]
        cur.execute(
            "UPDATE perfumes SET brand_id = %s WHERE name = %s",
            (brand_id, canonical_name),
        )
        log.info("Updated perfumes.brand_id for %r → brand %r (id=%s)",
                 canonical_name, correct_brand, brand_id)

    # Step C: update entity_market.brand_name for perfume rows
    for canonical_name, correct_brand in AFFECTED_PERFUMES.items():
        cur.execute(
            "UPDATE entity_market SET brand_name = %s "
            "WHERE canonical_name = %s AND entity_type = 'perfume'",
            (correct_brand, canonical_name),
        )
        log.info("Updated entity_market.brand_name for %r → %r", canonical_name, correct_brand)

    # Step D: delete signals under phantom brand UUIDs (FK to entity_market)
    if phantom_em_uuids:
        cur.execute(
            "DELETE FROM signals WHERE entity_id::text = ANY(%s)",
            (phantom_em_uuids,),
        )
        log.info("Deleted %d phantom brand signals", cur.rowcount)

    # Step E: delete timeseries under phantom brand UUIDs
    if phantom_em_uuids:
        cur.execute(
            "DELETE FROM entity_timeseries_daily WHERE entity_id::text = ANY(%s)",
            (phantom_em_uuids,),
        )
        log.info("Deleted %d phantom brand timeseries rows", cur.rowcount)

    # Step F: delete phantom brand entity_market rows
    if phantom_em_uuids:
        cur.execute(
            "DELETE FROM entity_market WHERE id::text = ANY(%s)",
            (phantom_em_uuids,),
        )
        log.info("Deleted %d phantom brand entity_market rows", cur.rowcount)

    # Step G: delete phantom market brand rows
    # Must come AFTER deleting dependent perfumes.brand_id links (done in Step B above)
    # and after phantom entity_market rows are gone (Step F).
    # Also need to check that no perfumes still reference these brand IDs.
    # phantom_brand_ids are UUID objects — cast explicitly for ANY() comparison.
    if phantom_brand_ids:
        cur.execute(
            "SELECT COUNT(*) FROM perfumes WHERE brand_id = ANY(%s::uuid[])",
            (phantom_brand_ids,),
        )
        remaining_perfume_refs = cur.fetchone()[0]
        if remaining_perfume_refs > 0:
            log.warning(
                "%d perfume rows still reference phantom brand IDs — skipping brand delete",
                remaining_perfume_refs,
            )
        else:
            cur.execute(
                "DELETE FROM brands WHERE id = ANY(%s::uuid[])",
                (phantom_brand_ids,),
            )
            log.info("Deleted %d phantom market brand rows", cur.rowcount)

    conn.commit()
    log.info("All changes committed.")
    conn.close()

    print()
    print(sep)
    print("APPLY COMPLETE")
    print(sep)
    print()
    print("Next step — re-run aggregation + signal detection for each affected date.")
    print("Run in order (aggregation first, then signals):")
    print()
    for d in RERUN_DATES:
        print(f"  DATABASE_URL=<prod-url> python3 -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics --date {d}")
    print()
    for d in RERUN_DATES:
        print(f"  DATABASE_URL=<prod-url> python3 -m perfume_trend_sdk.jobs.detect_breakout_signals --date {d}")
    print()
    print("Verification SQL — run after aggregation backfill:")
    print("""
  -- 1. Phantom brands gone
  SELECT COUNT(*) FROM brands WHERE name = ANY(ARRAY[
    'Armaf Club de','Armaf Club de Nuit Intense',
    'Al Haramain Amber','Paco Rabanne 1','Yves Saint Laurent Black'
  ]);  -- expect: 0

  -- 2. Phantom brand entity_market gone
  SELECT COUNT(*) FROM entity_market WHERE entity_id = ANY(ARRAY[
    'brand-armaf-club-de','brand-armaf-club-de-nuit-intense',
    'brand-al-haramain-amber','brand-paco-rabanne-1','brand-yves-saint-laurent-black'
  ]);  -- expect: 0

  -- 3. Affected perfumes now have correct brand_name
  SELECT canonical_name, brand_name FROM entity_market
  WHERE canonical_name = ANY(ARRAY[
    'Armaf Club de Nuit','Armaf Club de Nuit Intense Man',
    'Al Haramain Amber Oud','Paco Rabanne 1 Million','Yves Saint Laurent Black Opium'
  ]) AND entity_type = 'perfume';
  -- expect: all brand_names = Armaf / Al Haramain / Paco Rabanne / Yves Saint Laurent

  -- 4. Correct brand rollup entity_market rows exist
  SELECT entity_id, canonical_name FROM entity_market
  WHERE entity_type = 'brand' AND entity_id = ANY(ARRAY[
    'brand-armaf','brand-al-haramain','brand-paco-rabanne','brand-yves-saint-laurent'
  ]);  -- expect: 4 rows

  -- 5. No duplicate brand slugs
  SELECT slug, COUNT(*) FROM brands GROUP BY slug HAVING COUNT(*) > 1;  -- expect: 0
""")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "G2 Brand Mapping Remediation. "
            "Fixes truncated phantom brand rows created by the last-word-split heuristic. "
            "Default is DRY-RUN. Pass --apply to write."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write DB changes. Without this flag: dry-run only.",
    )
    args = parser.parse_args()

    if args.apply:
        log.warning("--apply flag active: will update brands, perfumes, entity_market in Postgres.")
    else:
        log.info("Dry-run mode (default): no DB writes.")

    run(apply=args.apply)
