#!/usr/bin/env python3
"""Phase G3-A — Batch Safe Alias Seed.

Generates and inserts safe resolver aliases for perfumes that currently have
zero or few alias entries, dramatically improving resolver hit rate.

Safety layers (applied in order):
  1. Form Guard   — alias must have ≥2 meaningful tokens, not start/end with
                    weak articles/prepositions, not consist only of generic words
  2. Uniqueness Guard (Tier B only) — bare perfume-name alias only when the
                    stripped perfume name is unique across all brands in the KB
  3. Collision Guard — normalized alias must not already exist in resolver_aliases
                    for ANY entity (prevents cross-entity collisions)

Alias tiers:
  Tier A — brand + stripped_perfume_name  (always generated when safe)
  Tier B — stripped_perfume_name only     (only when unique across all brands)

Usage:
  # Dry-run (no DB writes): inspect what would be inserted
  python3 scripts/generate_safe_aliases.py --dry-run

  # Dry-run with CSV output
  python3 scripts/generate_safe_aliases.py --dry-run --output-csv /tmp/g3a_aliases.csv

  # Apply to local SQLite resolver
  python3 scripts/generate_safe_aliases.py --apply

  # Apply in production (auto-detected via DATABASE_URL)
  DATABASE_URL=<prod-url> python3 scripts/generate_safe_aliases.py --apply

  # Bounded run
  python3 scripts/generate_safe_aliases.py --apply --limit 5000

  # Adjust sample size in dry-run output
  python3 scripts/generate_safe_aliases.py --dry-run --sample 200
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import time
import unicodedata
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterator, NamedTuple

# ---------------------------------------------------------------------------
# Inline normalize_text / strip_concentration — mirrors alias_generator.py
# exactly, but avoids importing the SDK package (script may run standalone).
# ---------------------------------------------------------------------------

_CONCENTRATION_SUFFIXES: tuple[str, ...] = (
    "extrait de parfum",
    "eau de parfum",
    "eau de toilette",
    "body spray",
    "body mist",
    "extrait",
    "parfum",
    "edp",
    "edt",
)


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).lower().strip()
    text = re.sub(r"'s\b", "", text)
    text = re.sub(r"'", " ", text)
    text = re.sub(r"[^\w\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _strip_concentration(perfume_name: str) -> str:
    name = perfume_name.strip()
    dash_match = re.match(
        r"^(.+?)\s*-\s*(?:" + "|".join(re.escape(s) for s in _CONCENTRATION_SUFFIXES) + r")\s*$",
        name,
        re.IGNORECASE,
    )
    if dash_match:
        return dash_match.group(1).strip()
    name_lower = name.lower()
    for suffix in _CONCENTRATION_SUFFIXES:
        if name_lower.endswith(" " + suffix):
            return name[: -(len(suffix) + 1)].strip()
        if name_lower == suffix:
            return name
    return name


# ---------------------------------------------------------------------------
# Form Guard constants
# ---------------------------------------------------------------------------

# Tokens that are too weak to start an alias (prepositions, articles, conjunctions)
_WEAK_STARTS: frozenset[str] = frozenset({
    "eau", "de", "the", "le", "la", "les", "des", "pour", "and", "or",
    "with", "for", "in", "a", "an", "un", "une", "du", "di", "al", "by",
    "my", "your", "our", "this", "that",
})

# Tokens that are too weak to end an alias
_WEAK_ENDS: frozenset[str] = frozenset({
    "eau", "de", "the", "le", "la", "pour", "and", "or", "with", "for",
    "in", "a", "an", "un", "une", "du", "di", "al", "by", "les", "des",
})

# Generic fragrance / product words — an alias consisting ONLY of these is noise
_GENERIC_TOKENS: frozenset[str] = frozenset({
    "perfume", "cologne", "fragrance", "parfum", "scent", "spray",
    "mist", "body", "lotion", "cream", "oil", "soap", "limited",
    "edition", "collection", "set", "gift", "travel",
    "original", "classic", "new", "modern",
})

# Maximum alias token length (extremely long aliases are suspect)
_MAX_TOKENS: int = 8


def _form_guard(alias: str) -> bool:
    """Return True when alias passes form quality checks."""
    tokens = alias.split()
    if len(tokens) < 2:
        return False
    if len(tokens) > _MAX_TOKENS:
        return False
    if tokens[0] in _WEAK_STARTS:
        return False
    if tokens[-1] in _WEAK_ENDS:
        return False
    # Must have at least one non-generic, non-weak token
    non_generic = [t for t in tokens if t not in _GENERIC_TOKENS and t not in _WEAK_STARTS]
    if len(non_generic) < 1:
        return False
    # Must contain at least one token with ≥2 alphabetic characters
    alpha_tokens = [t for t in tokens if sum(1 for c in t if c.isalpha()) >= 2]
    if not alpha_tokens:
        return False
    return True


# ---------------------------------------------------------------------------
# Data record
# ---------------------------------------------------------------------------

class AliasRecord(NamedTuple):
    alias_text: str           # display form (normalized)
    normalized_alias_text: str
    entity_type: str          # 'perfume' or 'brand'
    entity_id: int            # resolver_perfumes.id or resolver_brands.id
    canonical_name: str       # for reporting / CSV
    tier: str                 # 'A' (brand+perfume) or 'B' (perfume-only)
    match_type: str = "g3_safe_alias_seed"
    confidence: float = 0.85


# ---------------------------------------------------------------------------
# Backend — SQLite
# ---------------------------------------------------------------------------

def _load_sqlite(db_path: str):
    import sqlite3
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Load all existing normalized aliases → entity_id mapping (collision check)
    cur.execute("SELECT normalized_alias_text, entity_id FROM aliases")
    existing: dict[str, int] = {row[0]: row[1] for row in cur.fetchall()}

    # Load all perfumes from fragrance_master
    # fragrance_master has: perfume_id, brand_id, brand_name, perfume_name, canonical_name
    cur.execute(
        "SELECT perfume_id, brand_name, perfume_name, canonical_name FROM fragrance_master"
    )
    perfumes = cur.fetchall()

    conn.close()
    return existing, perfumes, "sqlite"


def _insert_sqlite(db_path: str, records: list[AliasRecord]) -> int:
    import sqlite3
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for rec in records:
        try:
            cur.execute(
                """
                INSERT OR IGNORE INTO aliases
                  (alias_text, normalized_alias_text, entity_type, entity_id,
                   match_type, confidence, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.alias_text,
                    rec.normalized_alias_text,
                    rec.entity_type,
                    rec.entity_id,
                    rec.match_type,
                    rec.confidence,
                    now, now,
                ),
            )
            if cur.rowcount:
                inserted += 1
        except Exception as exc:
            print(f"  [warn] insert failed for {rec.alias_text!r}: {exc}", file=sys.stderr)
    conn.commit()
    conn.close()
    return inserted


# ---------------------------------------------------------------------------
# Backend — PostgreSQL (psycopg2)
# ---------------------------------------------------------------------------

def _load_postgres(database_url: str):
    import psycopg2
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()

    # Load existing aliases (collision check)
    cur.execute(
        "SELECT normalized_alias_text, entity_id FROM resolver_aliases"
    )
    existing: dict[str, int] = {row[0]: row[1] for row in cur.fetchall()}

    # Load perfumes from resolver_fragrance_master
    cur.execute(
        """
        SELECT rfm.perfume_id, rfm.brand_name, rfm.perfume_name, rfm.canonical_name
        FROM resolver_fragrance_master rfm
        WHERE rfm.perfume_id IS NOT NULL
        """
    )
    perfumes = cur.fetchall()

    conn.close()
    return existing, perfumes, "postgres"


def _insert_postgres(database_url: str, records: list[AliasRecord]) -> int:
    import psycopg2
    import psycopg2.extras
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    now = datetime.now(timezone.utc)
    rows = [
        (
            rec.alias_text,
            rec.normalized_alias_text,
            rec.entity_type,
            rec.entity_id,
            rec.match_type,
            rec.confidence,
            now,
        )
        for rec in records
    ]
    inserted = 0
    batch_size = 500
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO resolver_aliases
              (alias_text, normalized_alias_text, entity_type, entity_id,
               match_type, confidence, created_at)
            VALUES %s
            ON CONFLICT (normalized_alias_text, entity_type, entity_id) DO NOTHING
            """,
            batch,
            page_size=batch_size,
        )
        inserted += cur.rowcount
        conn.commit()
    conn.close()
    return inserted


# ---------------------------------------------------------------------------
# Core generation logic
# ---------------------------------------------------------------------------

def _generate_candidates(
    perfumes: list,
    existing: dict[str, int],
    limit: int | None,
) -> tuple[list[AliasRecord], dict]:
    """
    Generate safe alias records.

    Returns:
        records  — list of AliasRecord to insert
        stats    — dict with breakdown counters
    """
    # --- Build uniqueness index: normalized_stripped_name → list of entity_ids ---
    # Tier B aliases are only generated when the stripped perfume name maps to
    # exactly one entity_id across the entire KB.
    name_to_ids: dict[str, list[int]] = defaultdict(list)
    for perfume_id, brand_name, perfume_name, canonical_name in perfumes:
        if not perfume_id or not perfume_name:
            continue
        stripped = _normalize(_strip_concentration(perfume_name))
        if stripped:
            name_to_ids[stripped].append(perfume_id)

    stats = {
        "total_perfumes": len(perfumes),
        "skipped_null": 0,
        "tier_a_generated": 0,
        "tier_a_form_fail": 0,
        "tier_a_collision": 0,
        "tier_b_generated": 0,
        "tier_b_not_unique": 0,
        "tier_b_form_fail": 0,
        "tier_b_collision": 0,
        "total_safe": 0,
    }

    records: list[AliasRecord] = []
    # Track aliases generated in this run to prevent intra-run duplicates
    seen_in_run: set[str] = set()

    processed = 0
    for perfume_id, brand_name, perfume_name, canonical_name in perfumes:
        if limit is not None and len(records) >= limit:
            break
        if not perfume_id or not perfume_name or not brand_name:
            stats["skipped_null"] += 1
            continue

        brand_norm = _normalize(brand_name)
        stripped_raw = _strip_concentration(perfume_name)
        stripped_norm = _normalize(stripped_raw)

        # --- Tier A: brand + stripped perfume name ---
        if stripped_norm:
            alias_a = f"{brand_norm} {stripped_norm}".strip()
            norm_a = alias_a  # already normalized
            if _form_guard(norm_a):
                if norm_a not in existing and norm_a not in seen_in_run:
                    rec = AliasRecord(
                        alias_text=alias_a,
                        normalized_alias_text=norm_a,
                        entity_type="perfume",
                        entity_id=perfume_id,
                        canonical_name=canonical_name or "",
                        tier="A",
                    )
                    records.append(rec)
                    seen_in_run.add(norm_a)
                    stats["tier_a_generated"] += 1
                else:
                    stats["tier_a_collision"] += 1
            else:
                stats["tier_a_form_fail"] += 1

        # --- Tier B: stripped perfume name only (uniqueness guard) ---
        if stripped_norm:
            ids_for_name = name_to_ids.get(stripped_norm, [])
            if len(ids_for_name) != 1:
                stats["tier_b_not_unique"] += 1
            elif not _form_guard(stripped_norm):
                stats["tier_b_form_fail"] += 1
            elif stripped_norm in existing or stripped_norm in seen_in_run:
                stats["tier_b_collision"] += 1
            else:
                rec = AliasRecord(
                    alias_text=stripped_norm,
                    normalized_alias_text=stripped_norm,
                    entity_type="perfume",
                    entity_id=perfume_id,
                    canonical_name=canonical_name or "",
                    tier="B",
                )
                records.append(rec)
                seen_in_run.add(stripped_norm)
                stats["tier_b_generated"] += 1

        processed += 1

    stats["total_safe"] = len(records)
    return records, stats


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

def _print_dry_run_report(
    records: list[AliasRecord],
    stats: dict,
    existing_count: int,
    backend: str,
    sample_n: int,
) -> None:
    tier_a = [r for r in records if r.tier == "A"]
    tier_b = [r for r in records if r.tier == "B"]

    token_hist: dict[int, int] = defaultdict(int)
    for r in records:
        token_hist[len(r.normalized_alias_text.split())] += 1

    print("=" * 68)
    print("Phase G3-A — Safe Alias Seed  DRY-RUN REPORT")
    print("=" * 68)
    print(f"Backend              : {backend}")
    print(f"Existing aliases     : {existing_count:,}")
    print()
    print("--- Generation stats ---")
    print(f"Total perfumes       : {stats['total_perfumes']:,}")
    print(f"Skipped (null data)  : {stats['skipped_null']:,}")
    print()
    print(f"Tier A (brand+name)")
    print(f"  Generated          : {stats['tier_a_generated']:,}")
    print(f"  Form fail          : {stats['tier_a_form_fail']:,}")
    print(f"  Collision skip     : {stats['tier_a_collision']:,}")
    print()
    print(f"Tier B (name only, unique)")
    print(f"  Generated          : {stats['tier_b_generated']:,}")
    print(f"  Not unique         : {stats['tier_b_not_unique']:,}")
    print(f"  Form fail          : {stats['tier_b_form_fail']:,}")
    print(f"  Collision skip     : {stats['tier_b_collision']:,}")
    print()
    print(f"Total safe to insert : {stats['total_safe']:,}")
    print(f"  Tier A             : {len(tier_a):,}")
    print(f"  Tier B             : {len(tier_b):,}")
    print()
    print("Token length distribution:")
    for n in sorted(token_hist):
        print(f"  {n} tokens          : {token_hist[n]:,}")
    print()

    alias_count_after = existing_count + stats["total_safe"]
    print(f"Aliases before       : {existing_count:,}")
    print(f"Aliases after        : {alias_count_after:,}")
    print(f"Net new              : +{stats['total_safe']:,}")
    print()

    sample = records[:sample_n]
    print(f"--- Sample aliases (first {len(sample)}) ---")
    for i, rec in enumerate(sample, 1):
        print(f"  [{i:3d}] [{rec.tier}] {rec.normalized_alias_text!r:50s}  → {rec.canonical_name}")
    print("=" * 68)


def _write_csv(records: list[AliasRecord], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "tier", "alias_text", "normalized_alias_text",
            "entity_type", "entity_id", "canonical_name",
            "match_type", "confidence",
        ])
        for rec in records:
            writer.writerow([
                rec.tier, rec.alias_text, rec.normalized_alias_text,
                rec.entity_type, rec.entity_id, rec.canonical_name,
                rec.match_type, rec.confidence,
            ])
    print(f"CSV written: {path}  ({len(records):,} rows)")


# ---------------------------------------------------------------------------
# Verification queries
# ---------------------------------------------------------------------------

def _verify_sqlite(db_path: str, before: int) -> None:
    import sqlite3
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM aliases")
    after = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM aliases WHERE match_type = 'g3_safe_alias_seed'")
    g3a = cur.fetchone()[0]
    cur.execute(
        """
        SELECT COUNT(DISTINCT entity_id) FROM aliases
        WHERE match_type = 'g3_safe_alias_seed'
        """
    )
    covered = cur.fetchone()[0]
    cur.execute("SELECT normalized_alias_text, COUNT(*) FROM aliases GROUP BY normalized_alias_text HAVING COUNT(*) > 1")
    dupes = cur.fetchall()
    conn.close()
    _print_verification(before, after, g3a, covered, dupes)


def _verify_postgres(database_url: str, before: int) -> None:
    import psycopg2
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM resolver_aliases")
    after = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM resolver_aliases WHERE match_type = 'g3_safe_alias_seed'")
    g3a = cur.fetchone()[0]
    cur.execute(
        """
        SELECT COUNT(DISTINCT entity_id) FROM resolver_aliases
        WHERE match_type = 'g3_safe_alias_seed'
        """
    )
    covered = cur.fetchone()[0]
    cur.execute(
        """
        SELECT normalized_alias_text, COUNT(*)
        FROM resolver_aliases
        GROUP BY normalized_alias_text
        HAVING COUNT(*) > 1
        """
    )
    dupes = cur.fetchall()
    conn.close()
    _print_verification(before, after, g3a, covered, dupes)


def _print_verification(before: int, after: int, g3a: int, covered: int, dupes: list) -> None:
    print()
    print("=== Verification ===")
    print(f"Aliases before       : {before:,}")
    print(f"Aliases after        : {after:,}")
    print(f"Net new              : +{after - before:,}")
    print(f"g3_safe_alias_seed   : {g3a:,}")
    print(f"Perfumes now covered : {covered:,}")
    print(f"Duplicate norm keys  : {len(dupes)} {'✅' if not dupes else '❌ PROBLEM'}")
    if dupes:
        for d in dupes[:10]:
            print(f"  {d[0]!r} × {d[1]}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Phase G3-A safe alias seed")
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="Report what would be inserted, no DB writes")
    parser.add_argument("--apply", action="store_true", default=False,
                        help="Write aliases to the resolver DB")
    parser.add_argument("--limit", type=int, default=None,
                        help="Maximum number of aliases to generate (for bounded test runs)")
    parser.add_argument("--sample", type=int, default=100,
                        help="Number of sample aliases to display in dry-run (default: 100)")
    parser.add_argument("--output-csv", metavar="FILE", default=None,
                        help="Write all candidate aliases to a CSV file")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("Specify --dry-run (no writes) or --apply (write aliases).")
        print("Add --output-csv FILE to save all candidates regardless of mode.")
        sys.exit(1)

    database_url = os.environ.get("DATABASE_URL", "")

    # --- Load ---
    t0 = time.time()
    if database_url:
        print(f"[g3a] Backend: PostgreSQL (DATABASE_URL set)")
        existing, perfumes, backend = _load_postgres(database_url)
    else:
        db_path = os.environ.get("RESOLVER_DB_PATH", "data/resolver/pti.db")
        print(f"[g3a] Backend: SQLite ({db_path})")
        existing, perfumes, backend = _load_sqlite(db_path)

    existing_count_before = len(existing)
    print(f"[g3a] Loaded {len(perfumes):,} perfumes, {existing_count_before:,} existing aliases")

    # --- Generate ---
    print("[g3a] Generating candidates …")
    records, stats = _generate_candidates(perfumes, existing, args.limit)
    elapsed = time.time() - t0
    print(f"[g3a] Generated {len(records):,} safe aliases in {elapsed:.1f}s")

    # --- CSV output (always, if requested) ---
    if args.output_csv:
        _write_csv(records, args.output_csv)

    # --- Dry-run report ---
    if args.dry_run:
        _print_dry_run_report(records, stats, existing_count_before, backend, args.sample)
        return

    # --- Apply ---
    if args.apply:
        if not records:
            print("[g3a] Nothing to insert — exiting.")
            return
        print(f"[g3a] Inserting {len(records):,} aliases …")
        t1 = time.time()
        if database_url:
            inserted = _insert_postgres(database_url, records)
        else:
            db_path = os.environ.get("RESOLVER_DB_PATH", "data/resolver/pti.db")
            inserted = _insert_sqlite(db_path, records)
        elapsed2 = time.time() - t1
        print(f"[g3a] Inserted {inserted:,} aliases in {elapsed2:.1f}s")

        # --- Verification ---
        if database_url:
            _verify_postgres(database_url, existing_count_before)
        else:
            db_path = os.environ.get("RESOLVER_DB_PATH", "data/resolver/pti.db")
            _verify_sqlite(db_path, existing_count_before)


if __name__ == "__main__":
    main()
