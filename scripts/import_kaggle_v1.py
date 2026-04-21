"""
Phase 5 — Catalog Expansion: Kaggle/Parfumo import into resolver KB.

Usage:
    python3 scripts/import_kaggle_v1.py --csv /path/to/parfumo_data_clean.csv --dry-run
    python3 scripts/import_kaggle_v1.py --csv /path/to/parfumo_data_clean.csv --limit 500
    python3 scripts/import_kaggle_v1.py --csv /path/to/parfumo_data_clean.csv  # full run

Targets data/resolver/pti.db (authoritative resolver KB).
All inserted rows tagged source='kaggle_v1'.
Rollback: DELETE FROM fragrance_master/perfumes/brands WHERE source='kaggle_v1'.
"""

import argparse
import csv
import hashlib
import re
import sqlite3
import unicodedata
from pathlib import Path

SOURCE_TAG = "kaggle_v1"
BATCH_SIZE = 500

CONC_SUFFIXES = [
    "extrait de parfum",
    "eau de parfum",
    "eau de toilette",
    "eau de cologne",
    "eau fraiche",
    "extrait",
    "parfum",
    "edp",
    "edt",
    "edc",
]

NOISE_PATTERNS = {"n/a", "na", "???", "unknown", "-", ""}
MIN_LEN = 2

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "resolver" / "pti.db"


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\w\s]", "", text)
    return text.strip()


def strip_concentration(name: str) -> str:
    n = normalize(name)
    changed = True
    while changed:
        changed = False
        for suffix in sorted(CONC_SUFFIXES, key=len, reverse=True):
            if n.endswith(suffix):
                candidate = n[: -len(suffix)].strip()
                if candidate:
                    n = candidate
                    changed = True
    return n


def load_csv(path: str, limit=None):
    rows = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            brand = (row.get("Brand") or "").strip()
            name = (row.get("Name") or "").strip()

            if not brand or brand.lower() in NOISE_PATTERNS:
                continue
            if not name or name.lower() in NOISE_PATTERNS:
                continue

            nb = normalize(brand)
            nn = strip_concentration(name)

            if len(nb) < MIN_LEN or len(nn) < MIN_LEN:
                continue

            rows.append(
                {
                    "brand_canonical": brand,
                    "brand_normalized": nb,
                    "perfume_canonical": name,
                    "perfume_normalized": nn,
                }
            )
            if limit and len(rows) >= limit:
                break
    return rows


def run(csv_path: str, dry_run: bool, limit=None):
    rows = load_csv(csv_path, limit=limit)
    print(f"Loaded {len(rows)} valid rows from CSV (limit={limit})")

    con = sqlite3.connect(str(DB_PATH))
    con.execute("PRAGMA journal_mode=WAL")
    cur = con.cursor()

    # ── Fetch existing normalized names ──────────────────────────────────────
    existing_brands: dict[str, int] = {
        r[0]: r[1]
        for r in cur.execute("SELECT normalized_name, id FROM brands").fetchall()
    }
    existing_perfumes: set[str] = {
        r[0]
        for r in cur.execute("SELECT normalized_name FROM perfumes").fetchall()
    }
    existing_fm: set[str] = {
        r[0]
        for r in cur.execute("SELECT normalized_name FROM fragrance_master").fetchall()
    }

    baseline_aliases = cur.execute("SELECT COUNT(*) FROM aliases").fetchone()[0]

    # ── Classify rows ─────────────────────────────────────────────────────────
    new_brands: dict[str, str] = {}          # normalized → canonical
    new_perfumes: list[dict] = []            # rows to insert
    skip_perfume_dup = 0
    skip_fm_dup = 0

    sample_insert: list[str] = []
    sample_skip: list[str] = []

    for r in rows:
        bn = r["brand_normalized"]
        bc = r["brand_canonical"]
        pn = r["perfume_normalized"]
        pc = r["perfume_canonical"]

        fm_key = f"{bn} {pn}"

        if pn in existing_perfumes:
            skip_perfume_dup += 1
            if len(sample_skip) < 10:
                sample_skip.append(f"  SKIP perfume dup | brand={bc!r} | name={pc!r}")
            continue

        if fm_key in existing_fm:
            skip_fm_dup += 1
            if len(sample_skip) < 10:
                sample_skip.append(f"  SKIP fm dup | brand={bc!r} | name={pc!r}")
            continue

        if bn not in existing_brands and bn not in new_brands:
            new_brands[bn] = bc

        if len(sample_insert) < 10:
            sample_insert.append(
                f"  INSERT | brand={bc!r} | perfume={pc!r} | norm={pn!r}"
            )

        new_perfumes.append(r)
        existing_perfumes.add(pn)   # prevent intra-batch dups
        existing_fm.add(fm_key)

    print()
    print("── DRY-RUN SUMMARY ─────────────────────────────────────────────" if dry_run else "── RUN SUMMARY ─────────────────────────────────────────────────")
    print(f"  new brands to insert:    {len(new_brands)}")
    print(f"  existing brands (skip):  {len([r for r in rows if r['brand_normalized'] in existing_brands and r['perfume_normalized'] in existing_perfumes])}")
    print(f"  new perfumes to insert:  {len(new_perfumes)}")
    print(f"  skip (perfume dup):      {skip_perfume_dup}")
    print(f"  skip (fm dup):           {skip_fm_dup}")
    print(f"  aliases (must stay):     {baseline_aliases}")
    print()
    print("Sample candidates for INSERT:")
    for s in sample_insert:
        print(s)
    print()
    print("Sample candidates for SKIP:")
    for s in sample_skip:
        print(s)

    if dry_run:
        print()
        print("DRY-RUN complete — no writes performed.")
        con.close()
        return {
            "new_brands": len(new_brands),
            "new_perfumes": len(new_perfumes),
            "skip_dup": skip_perfume_dup + skip_fm_dup,
            "aliases_unchanged": True,
            "dry_run": True,
        }

    # ── Real writes ──────────────────────────────────────────────────────────
    inserted_brands = 0
    inserted_perfumes = 0
    inserted_fm = 0
    errors = 0

    # Step 1: insert new brands
    brand_id_map: dict[str, int] = dict(existing_brands)  # normalized → id
    brand_batch = list(new_brands.items())
    for i in range(0, len(brand_batch), BATCH_SIZE):
        chunk = brand_batch[i : i + BATCH_SIZE]
        try:
            cur.executemany(
                "INSERT OR IGNORE INTO brands (canonical_name, normalized_name) VALUES (?, ?)",
                [(bc, bn) for bn, bc in chunk],
            )
            con.commit()
            # Refresh brand_id_map for newly inserted brands
            for bn, _ in chunk:
                row = cur.execute(
                    "SELECT id FROM brands WHERE normalized_name = ?", (bn,)
                ).fetchone()
                if row:
                    brand_id_map[bn] = row[0]
            inserted_brands += cur.rowcount
        except Exception as e:
            errors += 1
            print(f"  ERROR inserting brand batch {i}: {e}")
            con.rollback()

    print(f"Brands inserted: {inserted_brands} / {len(new_brands)}")

    # Step 2: insert perfumes
    perf_batch = new_perfumes
    fm_batch = []
    for i in range(0, len(perf_batch), BATCH_SIZE):
        chunk = perf_batch[i : i + BATCH_SIZE]
        try:
            for r in chunk:
                bn = r["brand_normalized"]
                bc = r["brand_canonical"]
                pn = r["perfume_normalized"]
                pc = r["perfume_canonical"]
                brand_id = brand_id_map.get(bn)

                cur.execute(
                    "INSERT OR IGNORE INTO perfumes (brand_id, canonical_name, normalized_name) VALUES (?, ?, ?)",
                    (brand_id, pc, pn),
                )
                perfume_id = cur.execute(
                    "SELECT id FROM perfumes WHERE normalized_name = ?", (pn,)
                ).fetchone()
                perfume_id = perfume_id[0] if perfume_id else None

                canonical_fm = f"{bc} {pc}"
                normalized_fm = f"{bn} {pn}"
                # Content-based fragrance_id: stable across runs, no collision risk
                fid_hash = hashlib.sha1(normalized_fm.encode()).hexdigest()[:12]
                fragrance_id = f"fm_{SOURCE_TAG}_{fid_hash}"
                fm_batch.append(
                    (
                        fragrance_id,
                        bc, pc, canonical_fm, normalized_fm,
                        SOURCE_TAG,
                        brand_id, perfume_id,
                    )
                )
            con.commit()
            inserted_perfumes += len(chunk)
        except Exception as e:
            errors += 1
            print(f"  ERROR inserting perfume batch {i}: {e}")
            con.rollback()

    print(f"Perfumes inserted: {inserted_perfumes} / {len(perf_batch)}")

    # Step 3: insert fragrance_master
    for i in range(0, len(fm_batch), BATCH_SIZE):
        chunk = fm_batch[i : i + BATCH_SIZE]
        try:
            cur.executemany(
                """INSERT OR IGNORE INTO fragrance_master
                   (fragrance_id, brand_name, perfume_name, canonical_name, normalized_name, source, brand_id, perfume_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                chunk,
            )
            con.commit()
            inserted_fm += cur.rowcount
        except Exception as e:
            errors += 1
            print(f"  ERROR inserting FM batch {i}: {e}")
            con.rollback()

    print(f"fragrance_master inserted: {inserted_fm} / {len(fm_batch)}")

    # ── Final verification ────────────────────────────────────────────────────
    final_aliases = cur.execute("SELECT COUNT(*) FROM aliases").fetchone()[0]
    dup_check = cur.execute(
        "SELECT COUNT(*) FROM (SELECT normalized_name FROM perfumes GROUP BY normalized_name HAVING COUNT(*) > 1)"
    ).fetchone()[0]

    print()
    print("── POST-RUN VERIFICATION ────────────────────────────────────────")
    print(f"  brands now:        {cur.execute('SELECT COUNT(*) FROM brands').fetchone()[0]}")
    print(f"  perfumes now:      {cur.execute('SELECT COUNT(*) FROM perfumes').fetchone()[0]}")
    print(f"  fragrance_master:  {cur.execute('SELECT COUNT(*) FROM fragrance_master').fetchone()[0]}")
    print(f"  aliases (must be unchanged): {final_aliases} {'✅' if final_aliases == baseline_aliases else '❌ CHANGED'}")
    print(f"  perfume duplicates: {dup_check} {'✅' if dup_check == 0 else '❌ HAS DUPS'}")
    print(f"  errors during run:  {errors}")

    con.close()
    return {
        "inserted_brands": inserted_brands,
        "inserted_perfumes": inserted_perfumes,
        "inserted_fm": inserted_fm,
        "errors": errors,
        "aliases_unchanged": final_aliases == baseline_aliases,
        "zero_dups": dup_check == 0,
    }


def rollback():
    """Remove all kaggle_v1 rows. Uses FM table to collect exact perfume/brand IDs first."""
    con = sqlite3.connect(str(DB_PATH))
    con.execute("PRAGMA journal_mode=WAL")
    cur = con.cursor()

    print(f"=== ROLLBACK source='{SOURCE_TAG}' ===")
    print()

    # Step 1: collect exact IDs from FM BEFORE deleting it
    perf_ids = [
        r[0] for r in cur.execute(
            f"SELECT DISTINCT perfume_id FROM fragrance_master WHERE source=? AND perfume_id IS NOT NULL",
            (SOURCE_TAG,),
        ).fetchall()
    ]
    brand_ids = [
        r[0] for r in cur.execute(
            f"SELECT DISTINCT brand_id FROM fragrance_master WHERE source=? AND brand_id IS NOT NULL",
            (SOURCE_TAG,),
        ).fetchall()
    ]

    before = {t: cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ["brands", "perfumes", "fragrance_master", "aliases"]}

    # Step 2: delete FM rows
    cur.execute(f"DELETE FROM fragrance_master WHERE source=?", (SOURCE_TAG,))
    del_fm = cur.rowcount
    con.commit()

    # Step 3: delete perfumes that are now unreferenced (only kaggle_v1 ones)
    if perf_ids:
        remaining_refs = {
            r[0] for r in cur.execute(
                "SELECT DISTINCT perfume_id FROM fragrance_master WHERE perfume_id IS NOT NULL"
            ).fetchall()
        }
        del_perf_ids = [pid for pid in perf_ids if pid not in remaining_refs]
        if del_perf_ids:
            cur.execute(
                f"DELETE FROM perfumes WHERE id IN ({','.join('?' * len(del_perf_ids))})",
                del_perf_ids,
            )
        del_perf = len(del_perf_ids)
    else:
        del_perf = 0
    con.commit()

    # Step 4: delete brands that are now unreferenced (only kaggle_v1 ones)
    if brand_ids:
        remaining_brand_refs = {
            r[0] for r in cur.execute(
                "SELECT DISTINCT brand_id FROM perfumes WHERE brand_id IS NOT NULL"
            ).fetchall()
        }
        remaining_brand_refs.update(
            r[0] for r in cur.execute(
                "SELECT DISTINCT brand_id FROM fragrance_master WHERE brand_id IS NOT NULL"
            ).fetchall()
        )
        del_brand_ids = [bid for bid in brand_ids if bid not in remaining_brand_refs]
        if del_brand_ids:
            cur.execute(
                f"DELETE FROM brands WHERE id IN ({','.join('?' * len(del_brand_ids))})",
                del_brand_ids,
            )
        del_brands = len(del_brand_ids)
    else:
        del_brands = 0
    con.commit()

    after = {t: cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
             for t in ["brands", "perfumes", "fragrance_master", "aliases"]}

    print(f"Deleted: {del_fm} FM rows, {del_perf} perfumes, {del_brands} brands")
    print()
    print("Before → After:")
    for t in ["brands", "perfumes", "fragrance_master", "aliases"]:
        ok = "✅" if after[t] == before[t] - (del_brands if t == "brands" else del_perf if t == "perfumes" else del_fm if t == "fragrance_master" else 0) else ""
        print(f"  {t}: {before[t]} → {after[t]} {ok}")

    # Dup check post-rollback
    dup = cur.execute("SELECT COUNT(*) FROM (SELECT normalized_name FROM perfumes GROUP BY normalized_name HAVING COUNT(*) > 1)").fetchone()[0]
    print(f"  perfume dups after rollback: {dup} {'✅' if dup == 0 else '❌'}")
    con.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--rollback", action="store_true", help="Remove all kaggle_v1 rows")
    args = parser.parse_args()

    if args.rollback:
        rollback()
        return

    if not args.csv:
        print("ERROR: --csv required unless --rollback")
        raise SystemExit(1)

    if not args.dry_run:
        print(f"TARGET: {DB_PATH}")
        print(f"SOURCE TAG: {SOURCE_TAG}")
        print(f"LIMIT: {args.limit or 'FULL'}")
        print()

    run(args.csv, dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
