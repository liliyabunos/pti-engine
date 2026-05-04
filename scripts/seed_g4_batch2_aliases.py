#!/usr/bin/env python3
"""
G4 Batch 2 — Arabic/ME Brand + Perfume Entity Seed

Creates missing Arabic/Middle Eastern perfume entities in the resolver KB and
adds clean Latin-only aliases that social media content uses.

Root cause addressed:
- G3-A generated mixed-script Tier A aliases (e.g. "khadlaj خدلج icon") instead of
  clean Latin aliases (e.g. "khadlaj icon") for brands with Arabic in canonical_name.
- "Afnan Perfumes" canonical name causes G3-A to generate "afnan perfumes supremacy"
  instead of "afnan supremacy".
- Maison Alhambra brand is entirely missing from resolver_brands.

Usage:
    # Dry-run (default)
    DATABASE_URL=<prod> python3 scripts/seed_g4_batch2_aliases.py

    # Apply
    DATABASE_URL=<prod> python3 scripts/seed_g4_batch2_aliases.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

MATCH_TYPE = "g4_batch2_seed"
SOURCE_TAG = "g4_batch2_seed"

# ── Known brand IDs (verified 2026-05-04) ─────────────────────────────────────
KNOWN_BRANDS: dict[str, int] = {
    "Afnan Perfumes": 628,      # "Afnan Perfumes" in resolver_brands
    "Khadlaj": 789,             # "Khadlaj / خدلج" in resolver_brands
    "Lattafa": 9,               # "Lattafa" in resolver_brands
    "Rasasi": 296,              # "Rasasi" in resolver_brands
    "Armaf": 1467,              # "Armaf" in resolver_brands
}

# ── Seed plan ──────────────────────────────────────────────────────────────────

# Brand aliases (Latin-only; mixed-script versions already exist from G3-A)
BRAND_ALIAS_SEEDS: list[dict] = [
    # afnan — brand "Afnan Perfumes" (id=628); social uses "afnan" (Latin-only)
    {"alias": "afnan",         "entity_id": 628, "entity_type": "brand",
     "reason": "Latin-only brand alias; g3_safe_alias_seed generated 'afnan perfumes' variants "
               "but social content uses bare 'afnan'"},
    # khadlaj — brand "Khadlaj / خدلج" (id=789); g3-a aliases are mixed-script
    {"alias": "khadlaj",       "entity_id": 789, "entity_type": "brand",
     "reason": "Latin-only brand alias; g3_safe_alias_seed generated 'khadlaj خدلج ...' "
               "which never matches Latin-only social content"},
]

# New entities: (canonical_name, brand_key, perfume_part, aliases_list, notes_text)
# brand_key = key in KNOWN_BRANDS or "Maison Alhambra" (created in this script)
NEW_ENTITIES: list[dict] = [
    # ── Afnan ──────────────────────────────────────────────────────────────────
    {
        "canonical_name": "Afnan Supremacy",
        "brand_key": "Afnan Perfumes",
        "perfume_part": "Supremacy",
        "aliases": ["afnan supremacy", "supremacy afnan"],
        "fragrance_id": "g4b2_afnan_supremacy",
        "audit_evidence": "17 occurrences, 15 distinct channels, clone/affordable content",
    },
    {
        "canonical_name": "Afnan 9pm",
        "brand_key": "Afnan Perfumes",
        "perfume_part": "9pm",
        "aliases": ["afnan 9pm", "9pm afnan"],
        "fragrance_id": "g4b2_afnan_9pm",
        "audit_evidence": "9 occurrences, 7 distinct channels (reddit), real perfume",
    },
    {
        "canonical_name": "Afnan Supremacy in Heaven",
        "brand_key": "Afnan Perfumes",
        "perfume_part": "Supremacy in Heaven",
        "aliases": ["afnan supremacy in heaven", "supremacy in heaven afnan"],
        "fragrance_id": "g4b2_afnan_supremacy_in_heaven",
        "audit_evidence": "7 occurrences, 4 distinct channels, separate SKU from base Supremacy",
    },
    # ── Khadlaj ────────────────────────────────────────────────────────────────
    {
        "canonical_name": "Khadlaj Icon",
        "brand_key": "Khadlaj",
        "perfume_part": "Icon",
        "aliases": ["khadlaj icon"],
        "fragrance_id": "g4b2_khadlaj_icon",
        "audit_evidence": "15 occurrences, 4 distinct channels; existing mixed-script "
                          "alias 'khadlaj خدلج icon' never matches Latin content",
    },
    {
        "canonical_name": "Khadlaj Island",
        "brand_key": "Khadlaj",
        "perfume_part": "Island",
        "aliases": ["khadlaj island"],
        "fragrance_id": "g4b2_khadlaj_island",
        "audit_evidence": "5 occurrences, 8 distinct channels (reddit), real perfume",
    },
    # ── Lattafa ────────────────────────────────────────────────────────────────
    {
        "canonical_name": "Lattafa Dynasty",
        "brand_key": "Lattafa",
        "perfume_part": "Dynasty",
        "aliases": ["lattafa dynasty", "dynasty lattafa"],
        "fragrance_id": "g4b2_lattafa_dynasty",
        "audit_evidence": "7 occurrences, 6 distinct channels, real perfume",
    },
    {
        "canonical_name": "Lattafa Asad",
        "brand_key": "Lattafa",
        "perfume_part": "Asad",
        "aliases": ["lattafa asad", "asad lattafa"],
        "fragrance_id": "g4b2_lattafa_asad",
        "audit_evidence": "6 occurrences, 8 distinct channels, real perfume (Arabic: lion)",
    },
    # ── Rasasi ─────────────────────────────────────────────────────────────────
    {
        "canonical_name": "Rasasi Fattan",
        "brand_key": "Rasasi",
        "perfume_part": "Fattan",
        "aliases": ["rasasi fattan", "fattan rasasi"],
        "fragrance_id": "g4b2_rasasi_fattan",
        "audit_evidence": "8 occurrences, 3 distinct channels, real perfume",
    },
    {
        "canonical_name": "Rasasi Daarej",
        "brand_key": "Rasasi",
        "perfume_part": "Daarej",
        "aliases": ["rasasi daarej", "daarej rasasi"],
        "fragrance_id": "g4b2_rasasi_daarej",
        "audit_evidence": "6 occurrences, 3 distinct channels, real perfume",
    },
    # ── Armaf ──────────────────────────────────────────────────────────────────
    {
        "canonical_name": "Armaf Odyssey",
        "brand_key": "Armaf",
        "perfume_part": "Odyssey",
        "aliases": ["armaf odyssey", "odyssey armaf"],
        "fragrance_id": "g4b2_armaf_odyssey",
        "audit_evidence": "5 occurrences, 3 distinct channels (reddit), real perfume",
    },
    # ── Maison Alhambra (brand missing from resolver_brands) ───────────────────
    {
        "canonical_name": "Maison Alhambra Jean Lowe",
        "brand_key": "Maison Alhambra",      # created by this script
        "perfume_part": "Jean Lowe",
        "aliases": ["maison alhambra jean lowe", "jean lowe alhambra"],
        "fragrance_id": "g4b2_alhambra_jean_lowe",
        "audit_evidence": "9 occurrences, 3 distinct channels, real perfume; "
                          "brand entirely missing from resolver_brands",
    },
]


def _connect() -> psycopg2.extensions.connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("[error] DATABASE_URL not set.", file=sys.stderr)
        sys.exit(1)
    return psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)


def _normalize(text: str) -> str:
    import unicodedata, re
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[''`]", "", text)
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _load_alias_lookup(cur) -> dict[str, int]:
    """Returns {normalized_alias_text: entity_id}."""
    cur.execute("SELECT normalized_alias_text, entity_id FROM resolver_aliases")
    return {row["normalized_alias_text"]: row["entity_id"] for row in cur.fetchall()}


def _get_or_create_brand(cur, brand_name: str, dry_run: bool) -> int | None:
    """Get brand_id from KNOWN_BRANDS or create if needed (Maison Alhambra)."""
    if brand_name in KNOWN_BRANDS:
        return KNOWN_BRANDS[brand_name]

    # Try to find in DB
    norm = _normalize(brand_name)
    cur.execute(
        "SELECT id, canonical_name FROM resolver_brands WHERE LOWER(canonical_name) = %s LIMIT 1",
        (brand_name.lower(),),
    )
    row = cur.fetchone()
    if row:
        print(f"  [brand] '{brand_name}' already exists: id={row['id']}")
        return row["id"]

    if dry_run:
        print(f"  [brand] WOULD CREATE brand: '{brand_name}'")
        return None

    # Insert
    cur.execute(
        """
        INSERT INTO resolver_brands (canonical_name, normalized_name)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
        RETURNING id
        """,
        (brand_name, norm),
    )
    row = cur.fetchone()
    if row:
        bid = row["id"]
        print(f"  [brand] CREATED '{brand_name}' → id={bid}")
        return bid
    # May have hit UNIQUE conflict
    cur.execute(
        "SELECT id FROM resolver_brands WHERE LOWER(canonical_name) = %s LIMIT 1",
        (brand_name.lower(),),
    )
    row = cur.fetchone()
    return row["id"] if row else None


def main() -> None:
    parser = argparse.ArgumentParser(description="G4 Batch 2 — Arabic/ME alias seed")
    parser.add_argument("--apply", action="store_true", default=False,
                        help="Write to DB (default: dry-run)")
    args = parser.parse_args()
    dry_run = not args.apply

    conn = _connect()
    cur = conn.cursor()

    print(f"[g4_batch2] mode: {'DRY-RUN' if dry_run else 'APPLY'}")
    print(f"[g4_batch2] match_type: {MATCH_TYPE}")
    print()

    # ── Snapshot counts ────────────────────────────────────────────────────────
    cur.execute("SELECT COUNT(*) AS c FROM resolver_aliases")
    before_aliases = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM resolver_perfumes")
    before_perfumes = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM resolver_brands")
    before_brands = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM resolver_fragrance_master")
    before_fm = cur.fetchone()["c"]

    print(f"[g4_batch2] Before: aliases={before_aliases}, perfumes={before_perfumes}, "
          f"brands={before_brands}, fm={before_fm}")
    print()

    # ── Load alias lookup (collision guard) ────────────────────────────────────
    alias_lookup = _load_alias_lookup(cur)
    in_run: set[str] = set()  # dedup within this run

    inserted_aliases = 0
    skipped_aliases = 0
    created_entities = 0
    created_brands = 0

    # ── 1. Brand-only aliases ──────────────────────────────────────────────────
    print("=== Brand Aliases ===")
    for seed in BRAND_ALIAS_SEEDS:
        norm_alias = _normalize(seed["alias"])
        entity_id = seed["entity_id"]
        entity_type = seed["entity_type"]
        reason = seed["reason"]

        if norm_alias in in_run:
            print(f"  SKIP (dup in-run) '{norm_alias}'")
            skipped_aliases += 1
            continue
        if norm_alias in alias_lookup:
            existing = alias_lookup[norm_alias]
            if existing == entity_id:
                print(f"  ALREADY EXISTS '{norm_alias}' → entity_id={entity_id}")
            else:
                print(f"  COLLISION '{norm_alias}' already points to entity_id={existing} "
                      f"(wanted {entity_id}) — SKIPPING")
            skipped_aliases += 1
            in_run.add(norm_alias)
            continue

        in_run.add(norm_alias)
        print(f"  {'WOULD INSERT' if dry_run else 'INSERTING'} brand alias: '{norm_alias}' "
              f"→ entity_id={entity_id} ({entity_type})")
        print(f"    reason: {reason}")

        if not dry_run:
            cur.execute(
                """
                INSERT INTO resolver_aliases
                    (alias_text, normalized_alias_text, entity_id, entity_type,
                     match_type, confidence)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (normalized_alias_text, entity_type, entity_id) DO NOTHING
                """,
                (seed["alias"], norm_alias, entity_id, entity_type, MATCH_TYPE, 0.90),
            )
            if cur.rowcount > 0:
                inserted_aliases += 1
                alias_lookup[norm_alias] = entity_id
            else:
                skipped_aliases += 1

        else:
            inserted_aliases += 1  # dry-run count

    print()

    # ── 2. New entities ────────────────────────────────────────────────────────
    print("=== New Entities ===")

    # Handle Maison Alhambra brand creation
    maison_alhambra_id: int | None = None
    if any(e["brand_key"] == "Maison Alhambra" for e in NEW_ENTITIES):
        print("[brand] Checking Maison Alhambra...")
        maison_alhambra_id = _get_or_create_brand(cur, "Maison Alhambra", dry_run)
        if not dry_run and maison_alhambra_id and maison_alhambra_id not in KNOWN_BRANDS.values():
            created_brands += 1
            # Add brand alias
            for ba in [("maison alhambra", maison_alhambra_id)]:
                norm_ba = _normalize(ba[0])
                if norm_ba not in alias_lookup and norm_ba not in in_run:
                    cur.execute(
                        """
                        INSERT INTO resolver_aliases
                            (alias_text, normalized_alias_text, entity_id, entity_type,
                             match_type, confidence)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (normalized_alias_text, entity_type, entity_id) DO NOTHING
                        """,
                        (ba[0], norm_ba, ba[1], "brand", MATCH_TYPE, 0.90),
                    )
                    if cur.rowcount > 0:
                        inserted_aliases += 1
                        alias_lookup[norm_ba] = ba[1]
                        in_run.add(norm_ba)
                        print(f"  [brand alias] INSERTED 'maison alhambra' → id={maison_alhambra_id}")
        elif dry_run:
            print(f"  [brand alias] WOULD INSERT 'maison alhambra' → (new brand)")
            inserted_aliases += 1  # count brand alias
        print()

    for entity in NEW_ENTITIES:
        canonical = entity["canonical_name"]
        brand_key = entity["brand_key"]
        perfume_part = entity["perfume_part"]
        aliases = entity["aliases"]
        fragrance_id = entity["fragrance_id"]
        evidence = entity["audit_evidence"]

        # Resolve brand_id
        if brand_key == "Maison Alhambra":
            brand_id = maison_alhambra_id
        else:
            brand_id = KNOWN_BRANDS.get(brand_key)

        if brand_id is None:
            print(f"  SKIP '{canonical}': no brand_id for '{brand_key}'")
            continue

        print(f"  {canonical} (brand_id={brand_id})")
        print(f"    evidence: {evidence}")

        # Check aliases for collisions
        valid_aliases = []
        for a in aliases:
            norm_a = _normalize(a)
            if norm_a in in_run:
                print(f"    SKIP alias '{norm_a}' (dup in-run)")
                continue
            if norm_a in alias_lookup:
                existing = alias_lookup[norm_a]
                print(f"    COLLISION alias '{norm_a}' already → entity_id={existing} — SKIP")
                in_run.add(norm_a)
                continue
            valid_aliases.append((a, norm_a))

        if not valid_aliases:
            print(f"    SKIP entity: all aliases collide or duplicate")
            skipped_aliases += len(aliases)
            continue

        if dry_run:
            print(f"    WOULD CREATE entity '{canonical}'")
            for _, norm_a in valid_aliases:
                print(f"    WOULD INSERT alias: '{norm_a}'")
                in_run.add(norm_a)
            created_entities += 1
            inserted_aliases += len(valid_aliases)
            continue

        # ── INSERT perfume ─────────────────────────────────────────────────────
        norm_canonical = _normalize(canonical)
        cur.execute(
            """
            INSERT INTO resolver_perfumes (canonical_name, normalized_name, brand_id)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            (canonical, norm_canonical, brand_id),
        )
        row = cur.fetchone()
        if row:
            perfume_id = row["id"]
            print(f"    CREATED resolver_perfumes id={perfume_id}")
        else:
            # Already exists — look it up
            cur.execute(
                "SELECT id FROM resolver_perfumes WHERE normalized_name = %s LIMIT 1",
                (norm_canonical,),
            )
            row2 = cur.fetchone()
            if row2:
                perfume_id = row2["id"]
                print(f"    already in resolver_perfumes id={perfume_id}")
            else:
                print(f"    ERROR: could not get perfume_id for '{canonical}'")
                continue

        # ── INSERT fragrance_master ────────────────────────────────────────────
        cur.execute(
            """
            INSERT INTO resolver_fragrance_master
                (fragrance_id, brand_name, perfume_name, canonical_name, normalized_name, source, perfume_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                fragrance_id,
                brand_key.replace("_", " "),  # use display brand name
                perfume_part,
                canonical,
                norm_canonical,
                SOURCE_TAG,
                perfume_id,
            ),
        )
        print(f"    INSERTED fragrance_master fragrance_id={fragrance_id}")
        created_entities += 1

        # ── INSERT aliases ─────────────────────────────────────────────────────
        for alias_text, norm_a in valid_aliases:
            cur.execute(
                """
                INSERT INTO resolver_aliases
                    (alias_text, normalized_alias_text, entity_id, entity_type,
                     match_type, confidence)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (normalized_alias_text, entity_type, entity_id) DO NOTHING
                """,
                (alias_text, norm_a, perfume_id, "perfume", MATCH_TYPE, 0.90),
            )
            if cur.rowcount > 0:
                inserted_aliases += 1
                alias_lookup[norm_a] = perfume_id
                in_run.add(norm_a)
                print(f"    INSERTED alias: '{norm_a}' → id={perfume_id}")
            else:
                skipped_aliases += 1
                print(f"    SKIP alias '{norm_a}': conflict")

        print()

    # ── Commit ─────────────────────────────────────────────────────────────────
    if not dry_run:
        conn.commit()

        # Verify
        cur.execute("SELECT COUNT(*) AS c FROM resolver_aliases")
        after_aliases = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) AS c FROM resolver_perfumes")
        after_perfumes = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) AS c FROM resolver_brands")
        after_brands = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) AS c FROM resolver_fragrance_master")
        after_fm = cur.fetchone()["c"]

        print()
        print("=== Verification ===")
        print(f"  resolver_aliases:         {before_aliases} → {after_aliases} (+{after_aliases - before_aliases})")
        print(f"  resolver_perfumes:        {before_perfumes} → {after_perfumes} (+{after_perfumes - before_perfumes})")
        print(f"  resolver_brands:          {before_brands} → {after_brands} (+{after_brands - before_brands})")
        print(f"  resolver_fragrance_master:{before_fm} → {after_fm} (+{after_fm - before_fm})")

        # g4_batch2_seed rows
        cur.execute(
            "SELECT COUNT(*) AS c FROM resolver_aliases WHERE match_type = %s",
            (MATCH_TYPE,),
        )
        print(f"  {MATCH_TYPE} aliases: {cur.fetchone()['c']}")

        cur.execute(
            "SELECT COUNT(*) AS c FROM resolver_fragrance_master WHERE source = %s",
            (SOURCE_TAG,),
        )
        print(f"  {SOURCE_TAG} fragrance_master: {cur.fetchone()['c']}")

        # Duplicate check
        cur.execute("""
            SELECT COUNT(*) AS dups FROM (
                SELECT normalized_alias_text
                FROM resolver_aliases
                GROUP BY normalized_alias_text
                HAVING COUNT(*) > 1
            ) x
        """)
        dups = cur.fetchone()["dups"]
        print(f"  Duplicate normalized aliases: {dups}  (must be 0)")

        print()
        print("[g4_batch2] Rollback if needed:")
        print(f"  DELETE FROM resolver_aliases WHERE match_type = '{MATCH_TYPE}';")
        print(f"  DELETE FROM resolver_perfumes WHERE id IN (")
        print(f"    SELECT perfume_id FROM resolver_fragrance_master WHERE source = '{SOURCE_TAG}' AND perfume_id IS NOT NULL);")
        print(f"  DELETE FROM resolver_fragrance_master WHERE source = '{SOURCE_TAG}';")
        print(f"  DELETE FROM resolver_brands WHERE canonical_name = 'Maison Alhambra';  -- if created")

    else:
        print()
        print(f"[g4_batch2] DRY-RUN summary:")
        print(f"  Would insert {inserted_aliases} aliases")
        print(f"  Would create {created_entities} perfume entities")
        print(f"  Would create {created_brands} brands (Maison Alhambra)")
        print()
        print("  Run with --apply to write to DB.")

    conn.close()


if __name__ == "__main__":
    main()
