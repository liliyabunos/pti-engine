#!/usr/bin/env python3
"""
scripts/seed_g2_aliases.py — Phase G2 Targeted Alias Expansion

Adds a curated set of high-value aliases to resolver_aliases to improve
resolver recall for Arabic/ME brands, popular fragrances, and shorthand
terms surfaced by Phase G1 YouTube query expansion.

Default mode: DRY-RUN (read-only, zero DB writes).
Use --apply to execute the inserts.

All rows written use match_type='g2_seed' for easy rollback:
    DELETE FROM resolver_aliases WHERE match_type = 'g2_seed';

Idempotent: ON CONFLICT (normalized_alias_text, entity_type, entity_id)
DO NOTHING — safe to re-run any number of times.

Self-contained: uses psycopg2 directly (no SDK dependency).
Reads DATABASE_URL from environment (or PTI_DB_PATH for SQLite dev).
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s %(levelname)-7s %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Normalization
# Mirrors perfume_trend_sdk/utils/alias_generator.py:normalize_text exactly.
# Must stay in sync — the resolver hot-path uses the same normalization when
# writing normalized_alias_text to resolver_aliases.
# ---------------------------------------------------------------------------

def _normalize(value: str) -> str:
    """Normalize to match resolver_aliases.normalized_alias_text convention."""
    text = unicodedata.normalize("NFKC", value).lower().strip()
    text = re.sub(r"'s\b", "", text)       # amouage's → amouage
    text = re.sub(r"'", " ", text)         # d'hermes → d hermes
    text = re.sub(r"[^\w\s]+", " ", text)  # strip all remaining punctuation
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Target definitions
# ---------------------------------------------------------------------------

@dataclass
class AliasTarget:
    alias_text: str        # display form (written to alias_text column as-is)
    entity_type: str       # 'perfume' or 'brand'
    canonical_target: str  # full canonical name to look up in resolver tables


TARGETS: list[AliasTarget] = [
    # ── Lattafa ───────────────────────────────────────────────────────────
    AliasTarget("lattafa",          "brand",   "Lattafa"),
    AliasTarget("oud mood",         "perfume", "Lattafa Oud Mood"),
    AliasTarget("lattafa oud mood", "perfume", "Lattafa Oud Mood"),
    AliasTarget("khamrah",          "perfume", "Lattafa Khamrah"),
    AliasTarget("lattafa khamrah",  "perfume", "Lattafa Khamrah"),
    AliasTarget("yara",             "perfume", "Lattafa Yara"),
    AliasTarget("lattafa yara",     "perfume", "Lattafa Yara"),

    # ── Armaf ─────────────────────────────────────────────────────────────
    AliasTarget("armaf",                          "brand",   "Armaf"),
    AliasTarget("club de nuit",                   "perfume", "Armaf Club de Nuit"),
    AliasTarget("armaf club de nuit",             "perfume", "Armaf Club de Nuit"),
    AliasTarget("club de nuit intense man",       "perfume", "Armaf Club de Nuit Intense Man"),
    AliasTarget("armaf club de nuit intense man", "perfume", "Armaf Club de Nuit Intense Man"),

    # ── Rasasi ────────────────────────────────────────────────────────────
    AliasTarget("rasasi",       "brand",   "Rasasi"),
    AliasTarget("hawas",        "perfume", "Rasasi Hawas"),
    AliasTarget("rasasi hawas", "perfume", "Rasasi Hawas"),

    # ── Al Haramain ───────────────────────────────────────────────────────
    AliasTarget("al haramain",           "brand",   "Al Haramain"),
    AliasTarget("amber oud",             "perfume", "Al Haramain Amber Oud"),
    AliasTarget("al haramain amber oud", "perfume", "Al Haramain Amber Oud"),

    # ── Ajmal ─────────────────────────────────────────────────────────────
    AliasTarget("ajmal",       "brand",   "Ajmal"),
    AliasTarget("ajmal evoke", "perfume", "Ajmal Evoke"),

    # ── Swiss Arabian / Arabian Oud ───────────────────────────────────────
    AliasTarget("swiss arabian", "brand", "Swiss Arabian"),
    AliasTarget("arabian oud",   "brand", "Arabian Oud"),

    # ── By Kilian ─────────────────────────────────────────────────────────
    AliasTarget("angels share",        "perfume", "By Kilian Angels' Share"),
    AliasTarget("kilian angels share", "perfume", "By Kilian Angels' Share"),

    # ── Paco Rabanne ──────────────────────────────────────────────────────
    AliasTarget("1 million",              "perfume", "Paco Rabanne 1 Million"),
    AliasTarget("paco rabanne 1 million", "perfume", "Paco Rabanne 1 Million"),

    # ── YSL Black Opium ───────────────────────────────────────────────────
    AliasTarget("black opium",     "perfume", "Yves Saint Laurent Black Opium"),
    AliasTarget("ysl black opium", "perfume", "Yves Saint Laurent Black Opium"),

    # ── Initio ────────────────────────────────────────────────────────────
    AliasTarget("initio side effect", "perfume", "Initio Side Effect"),

    # ── Mancera ───────────────────────────────────────────────────────────
    AliasTarget("cedrat boise",         "perfume", "Mancera Cedrat Boise"),
    AliasTarget("mancera cedrat boise", "perfume", "Mancera Cedrat Boise"),

    # ── MFK BR540 shorthands ──────────────────────────────────────────────
    AliasTarget("rouge 540", "perfume", "Maison Francis Kurkdjian Baccarat Rouge 540"),
    AliasTarget("br540",     "perfume", "Maison Francis Kurkdjian Baccarat Rouge 540"),
]


# ---------------------------------------------------------------------------
# Result record
# ---------------------------------------------------------------------------

@dataclass
class AliasResult:
    alias_text: str
    normalized_alias: str
    entity_type: str
    canonical_target: str
    entity_id: Optional[int]
    status: str  # MISSING | AMBIGUOUS | EXISTING | WOULD_INSERT | INSERTED


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------

def _get_connection():
    """Return a psycopg2 connection using DATABASE_URL from environment."""
    import psycopg2
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        log.error(
            "DATABASE_URL is not set. "
            "Set it to your production Postgres URL and re-run, e.g.:\n"
            "  DATABASE_URL=postgresql://... python3 scripts/seed_g2_aliases.py"
        )
        sys.exit(1)
    if database_url.startswith("sqlite"):
        log.error("This script requires PostgreSQL. DATABASE_URL points to SQLite.")
        sys.exit(1)
    # Strip psycopg2-incompatible prefix variants
    if database_url.startswith("postgresql+psycopg2://"):
        database_url = database_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    log.info("Connecting to Postgres at ...%s", database_url.split("@")[-1] if "@" in database_url else database_url)
    return psycopg2.connect(database_url)


# ---------------------------------------------------------------------------
# DB lookup helpers
# ---------------------------------------------------------------------------

def _lookup_entity(cur, entity_type: str, canonical_target: str) -> tuple[Optional[int], str]:
    """
    Return (entity_id, status) where status is 'found' | 'missing' | 'ambiguous'.

    Brands   → resolver_brands.normalized_name
    Perfumes → resolver_perfumes.normalized_name, with resolver_fragrance_master fallback.
    """
    norm = _normalize(canonical_target)

    if entity_type == "brand":
        cur.execute(
            "SELECT id FROM resolver_brands WHERE normalized_name = %s", (norm,)
        )
        rows = cur.fetchall()
        if not rows:
            return None, "missing"
        if len(rows) > 1:
            return None, "ambiguous"
        return rows[0][0], "found"

    # perfume — try resolver_perfumes first
    cur.execute(
        "SELECT id FROM resolver_perfumes WHERE normalized_name = %s", (norm,)
    )
    rows = cur.fetchall()
    if len(rows) == 1:
        return rows[0][0], "found"
    if len(rows) > 1:
        return None, "ambiguous"

    # Fallback: resolver_fragrance_master → perfume_id
    cur.execute(
        "SELECT DISTINCT perfume_id FROM resolver_fragrance_master "
        "WHERE normalized_name = %s AND perfume_id IS NOT NULL",
        (norm,),
    )
    rows = cur.fetchall()
    if not rows:
        return None, "missing"
    ids = list({r[0] for r in rows})
    if len(ids) > 1:
        return None, "ambiguous"
    return ids[0], "found"


def _alias_exists(cur, normalized_alias: str, entity_type: str, entity_id: int) -> bool:
    cur.execute(
        "SELECT 1 FROM resolver_aliases "
        "WHERE normalized_alias_text = %s AND entity_type = %s AND entity_id = %s "
        "LIMIT 1",
        (normalized_alias, entity_type, entity_id),
    )
    return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(apply: bool) -> None:
    conn = _get_connection()
    results: list[AliasResult] = []

    try:
        # ── Phase 1: Read-only audit ──────────────────────────────────────
        log.info("Phase 1 — Audit (%d targets, dry_run=%s)", len(TARGETS), not apply)
        cur = conn.cursor()

        for t in TARGETS:
            norm_alias = _normalize(t.alias_text)
            entity_id, lookup_status = _lookup_entity(cur, t.entity_type, t.canonical_target)

            if lookup_status in ("missing", "ambiguous"):
                results.append(AliasResult(
                    alias_text=t.alias_text,
                    normalized_alias=norm_alias,
                    entity_type=t.entity_type,
                    canonical_target=t.canonical_target,
                    entity_id=None,
                    status=lookup_status.upper(),
                ))
                log.info("  [%-9s] %-35s -> %s", lookup_status.upper(), t.alias_text, t.canonical_target)
                continue

            exists = _alias_exists(cur, norm_alias, t.entity_type, entity_id)
            if exists:
                results.append(AliasResult(
                    alias_text=t.alias_text,
                    normalized_alias=norm_alias,
                    entity_type=t.entity_type,
                    canonical_target=t.canonical_target,
                    entity_id=entity_id,
                    status="EXISTING",
                ))
                log.info(
                    "  [EXISTING  ] %-35s -> %s (id=%d)",
                    t.alias_text, t.canonical_target, entity_id,
                )
                continue

            results.append(AliasResult(
                alias_text=t.alias_text,
                normalized_alias=norm_alias,
                entity_type=t.entity_type,
                canonical_target=t.canonical_target,
                entity_id=entity_id,
                status="WOULD_INSERT",
            ))
            log.info(
                "  [WOULD_INS ] %-35s -> %s (id=%d)",
                t.alias_text, t.canonical_target, entity_id,
            )

        # ── Phase 2: Write pass (--apply only) ────────────────────────────
        db_writes = 0
        if apply:
            to_insert = [r for r in results if r.status == "WOULD_INSERT"]
            log.info("Phase 2 — Writing %d rows to resolver_aliases", len(to_insert))
            for r in to_insert:
                cur.execute(
                    """
                    INSERT INTO resolver_aliases
                        (alias_text, normalized_alias_text, entity_type,
                         entity_id, match_type, confidence)
                    VALUES (%s, %s, %s, %s, 'g2_seed', 0.95)
                    ON CONFLICT (normalized_alias_text, entity_type, entity_id)
                    DO NOTHING
                    """,
                    (r.alias_text, r.normalized_alias, r.entity_type, r.entity_id),
                )
                r.status = "INSERTED"
                db_writes += 1
            conn.commit()
            log.info("Phase 2 — %d rows committed.", db_writes)
        else:
            conn.rollback()  # explicit: no writes were made
            log.info("Phase 2 — SKIPPED (dry-run).")

    finally:
        conn.close()

    # ── Summary ───────────────────────────────────────────────────────────
    total       = len(results)
    n_found     = sum(1 for r in results if r.status not in ("MISSING", "AMBIGUOUS"))
    n_missing   = sum(1 for r in results if r.status == "MISSING")
    n_ambiguous = sum(1 for r in results if r.status == "AMBIGUOUS")
    n_existing  = sum(1 for r in results if r.status == "EXISTING")
    n_would_ins = sum(1 for r in results if r.status == "WOULD_INSERT")
    n_inserted  = sum(1 for r in results if r.status == "INSERTED")

    sep = "=" * 64
    print()
    print(sep)
    print(f"Phase G2 Alias Seed — {'** DRY RUN ** (no writes)' if not apply else 'APPLIED'}")
    print(sep)
    print(f"  Total targets     : {total}")
    print(f"  Found in KB       : {n_found}")
    print(f"  MISSING  (skip)   : {n_missing}")
    print(f"  AMBIGUOUS (skip)  : {n_ambiguous}")
    print(f"  Already existing  : {n_existing}")
    print(f"  Would insert      : {n_would_ins}")
    print(f"  Inserted          : {n_inserted}")
    print(f"  DB writes         : {'YES — ' + str(n_inserted) + ' rows' if n_inserted else 'NO'}")
    print(sep)

    if n_missing:
        print("\nMISSING targets (canonical not found in resolver KB):")
        for r in results:
            if r.status == "MISSING":
                print(f"  MISSING   [{r.entity_type:7s}] {r.alias_text!r:35s} -> {r.canonical_target!r}")

    if n_ambiguous:
        print("\nAMBIGUOUS targets (multiple KB rows matched — skipped):")
        for r in results:
            if r.status == "AMBIGUOUS":
                print(f"  AMBIGUOUS [{r.entity_type:7s}] {r.alias_text!r:35s} -> {r.canonical_target!r}")

    print(f"\nWould-insert / Inserted rows ({n_would_ins + n_inserted} total):")
    for r in results:
        if r.status in ("WOULD_INSERT", "INSERTED"):
            print(
                f"  {r.status:12s} [{r.entity_type:7s}] "
                f"{r.alias_text!r:35s} -> {r.canonical_target!r} (entity_id={r.entity_id})"
            )

    if not apply:
        print()
        print("Dry-run complete — zero DB writes performed.")
        print("To apply: DATABASE_URL=... python3 scripts/seed_g2_aliases.py --apply")
        print()
        print("Rollback command (if needed after --apply):")
        print("  DELETE FROM resolver_aliases WHERE match_type = 'g2_seed';")

    if n_missing == total:
        log.error("All %d targets MISSING — verify DATABASE_URL and resolver table state.", total)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Phase G2: Seed targeted aliases into resolver_aliases. "
            "Default is DRY-RUN (read-only). Pass --apply to write."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write aliases to resolver_aliases. Without this flag: dry-run only.",
    )
    args = parser.parse_args()

    if args.apply:
        log.warning("--apply flag active: will write to resolver_aliases.")
    else:
        log.info("Dry-run mode (default): no DB writes will occur.")

    run(apply=args.apply)
