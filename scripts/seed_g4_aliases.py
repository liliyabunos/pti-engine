#!/usr/bin/env python3
"""
scripts/seed_g4_aliases.py — Phase G4 Batch 1 Alias Seed

Adds 4 approved high-value aliases to resolver_aliases that were identified
in the G4 candidate promotion audit.  These are ALIAS_TO_EXISTING entries only:
no new resolver_perfumes, no new resolver_brands, no entity creation.

Default mode: DRY-RUN (read-only, zero DB writes).
Use --apply to execute the inserts.

All rows written use match_type='g4_seed' for easy rollback:
    DELETE FROM resolver_aliases WHERE match_type = 'g4_seed';

Idempotent: ON CONFLICT (normalized_alias_text, entity_type, entity_id)
DO NOTHING — safe to re-run any number of times.

Self-contained: uses psycopg2 directly (no SDK dependency).
Reads DATABASE_URL from environment.

Approved G4 Batch 1 allowlist:
  1. baccarat rouge 540 edp  → perfume id=2  (MFK Baccarat Rouge 540)
  2. rouge 540 edp           → perfume id=2  (MFK Baccarat Rouge 540)
  3. ds durga                → brand   id=370 (D.S. & Durga)
  4. by lattafa              → brand   id=9   (Lattafa)

Explicitly excluded (not safe for alias-only addition):
  - nuit intense             (ambiguous across CDN Intense variants)
  - good girl                (no base Good Girl entity in KB)
  - carolina herrera good girl (same)
  - maison margiela replica  (Replica is a line, not a single perfume)
  - all dupe/context terms
  - bare concentration terms (edp, eau de parfum, extrait, intense)
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
# Must stay in sync with the resolver hot-path normalization.
# ---------------------------------------------------------------------------

def _normalize(value: str) -> str:
    """Normalize to match resolver_aliases.normalized_alias_text convention."""
    text = unicodedata.normalize("NFKC", value).lower().strip()
    text = re.sub(r"'s\b", "", text)       # amouage's → amouage
    text = re.sub(r"'", " ", text)         # d'hermes → d hermes
    text = re.sub(r"[^\w\s]+", " ", text)  # strip remaining punctuation
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Approved G4 Batch 1 allowlist (hardcoded — no dynamic loading)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AliasTarget:
    alias_text: str        # display form → written to alias_text column
    entity_type: str       # 'perfume' or 'brand'
    entity_id: int         # known resolver entity id (verified during audit)
    canonical_verify: str  # expected canonical name — used for verification only


TARGETS: list[AliasTarget] = [
    # ── MFK Baccarat Rouge 540 EDP shorthands ────────────────────────────
    AliasTarget(
        alias_text="baccarat rouge 540 edp",
        entity_type="perfume",
        entity_id=2,
        canonical_verify="Maison Francis Kurkdjian Baccarat Rouge 540",
    ),
    AliasTarget(
        alias_text="rouge 540 edp",
        entity_type="perfume",
        entity_id=2,
        canonical_verify="Maison Francis Kurkdjian Baccarat Rouge 540",
    ),
    # ── D.S. & Durga brand shorthand ─────────────────────────────────────
    AliasTarget(
        alias_text="ds durga",
        entity_type="brand",
        entity_id=370,
        canonical_verify="D.S. & Durga",
    ),
    # ── Lattafa brand "by X" variant ─────────────────────────────────────
    AliasTarget(
        alias_text="by lattafa",
        entity_type="brand",
        entity_id=9,
        canonical_verify="Lattafa",
    ),
]

MATCH_TYPE = "g4_seed"
CONFIDENCE = 0.90


# ---------------------------------------------------------------------------
# Result record
# ---------------------------------------------------------------------------

@dataclass
class AliasResult:
    alias_text: str
    normalized_alias: str
    entity_type: str
    entity_id: int
    canonical_verify: str
    status: str  # MISSING_TARGET | VERIFY_MISMATCH | CONFLICT_OTHER_ENTITY |
                 # EXISTING | WOULD_INSERT | INSERTED


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------

def _get_connection():
    """Return a psycopg2 connection using DATABASE_URL from environment."""
    import psycopg2
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        log.error(
            "DATABASE_URL is not set.\n"
            "For Railway dry-run: railway run --service pipeline-daily -- python3 scripts/seed_g4_aliases.py\n"
            "For local with public URL: DATABASE_URL=postgresql://... python3 scripts/seed_g4_aliases.py"
        )
        sys.exit(1)
    if database_url.startswith("sqlite"):
        log.error("This script requires PostgreSQL. DATABASE_URL points to SQLite.")
        sys.exit(1)
    # Strip psycopg2-incompatible prefix variants
    if database_url.startswith("postgresql+psycopg2://"):
        database_url = database_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    log.info("Connecting to Postgres at ...%s", database_url.split("@")[-1] if "@" in database_url else "[url]")
    import psycopg2
    return psycopg2.connect(database_url)


# ---------------------------------------------------------------------------
# DB lookup helpers
# ---------------------------------------------------------------------------

def _verify_entity(cur, entity_type: str, entity_id: int, canonical_verify: str) -> tuple[bool, str]:
    """
    Confirm entity_id exists in the resolver and its canonical name is close
    to canonical_verify.

    Returns (ok, actual_canonical_or_error).
    """
    if entity_type == "brand":
        cur.execute(
            "SELECT canonical_name FROM resolver_brands WHERE id = %s", (entity_id,)
        )
        row = cur.fetchone()
        if row is None:
            return False, f"brand id={entity_id} not found in resolver_brands"
        actual = row[0]
    else:
        # For perfumes, check resolver_fragrance_master for the canonical display name
        cur.execute(
            """
            SELECT rfm.brand_name || ' ' || rfm.perfume_name AS canonical
            FROM resolver_fragrance_master rfm
            WHERE rfm.perfume_id = %s
            LIMIT 1
            """,
            (entity_id,),
        )
        row = cur.fetchone()
        if row is None:
            # Fallback: resolver_perfumes.canonical_name
            cur.execute(
                "SELECT canonical_name FROM resolver_perfumes WHERE id = %s", (entity_id,)
            )
            row = cur.fetchone()
            if row is None:
                return False, f"perfume id={entity_id} not found in resolver_perfumes"
        actual = row[0]

    # Loose match: canonical_verify must appear as a substring of actual (case-insensitive)
    # or actual must contain the key words from canonical_verify
    verify_norm = _normalize(canonical_verify)
    actual_norm = _normalize(actual)
    if verify_norm in actual_norm or actual_norm in verify_norm:
        return True, actual
    # Secondary check: all words of canonical_verify appear in actual
    verify_words = set(verify_norm.split())
    actual_words = set(actual_norm.split())
    if verify_words.issubset(actual_words):
        return True, actual
    return False, f"actual='{actual}' does not match verify='{canonical_verify}'"


def _check_alias(cur, normalized_alias: str, entity_type: str, entity_id: int) -> str:
    """
    Check current state of alias in resolver_aliases.

    Returns:
      'none'                  — alias does not exist (safe to insert)
      'existing_same_entity'  — alias already points to this entity (skip)
      'conflict_other_entity' — alias points to a DIFFERENT entity (skip with warning)
    """
    cur.execute(
        """
        SELECT entity_id FROM resolver_aliases
        WHERE normalized_alias_text = %s AND entity_type = %s
        LIMIT 5
        """,
        (normalized_alias, entity_type),
    )
    rows = cur.fetchall()
    if not rows:
        return "none"
    existing_ids = {r[0] for r in rows}
    if entity_id in existing_ids:
        return "existing_same_entity"
    return "conflict_other_entity"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(apply: bool) -> None:
    conn = _get_connection()
    results: list[AliasResult] = []

    try:
        cur = conn.cursor()

        # ── Phase 1: Read-only audit ──────────────────────────────────────
        log.info(
            "Phase 1 — Audit (%d targets, dry_run=%s, match_type=%s)",
            len(TARGETS), not apply, MATCH_TYPE,
        )

        for t in TARGETS:
            norm_alias = _normalize(t.alias_text)

            # Step 1: verify entity exists and canonical matches
            entity_ok, detail = _verify_entity(cur, t.entity_type, t.entity_id, t.canonical_verify)
            if not entity_ok:
                results.append(AliasResult(
                    alias_text=t.alias_text,
                    normalized_alias=norm_alias,
                    entity_type=t.entity_type,
                    entity_id=t.entity_id,
                    canonical_verify=t.canonical_verify,
                    status="MISSING_TARGET",
                ))
                log.warning(
                    "  [MISSING_TARGET  ] %-32s id=%-5d  %s",
                    t.alias_text, t.entity_id, detail,
                )
                continue

            # Step 2: check for existing / conflicting alias
            alias_state = _check_alias(cur, norm_alias, t.entity_type, t.entity_id)

            if alias_state == "existing_same_entity":
                results.append(AliasResult(
                    alias_text=t.alias_text,
                    normalized_alias=norm_alias,
                    entity_type=t.entity_type,
                    entity_id=t.entity_id,
                    canonical_verify=t.canonical_verify,
                    status="EXISTING",
                ))
                log.info(
                    "  [EXISTING        ] %-32s -> %s (id=%d)",
                    t.alias_text, detail, t.entity_id,
                )
                continue

            if alias_state == "conflict_other_entity":
                results.append(AliasResult(
                    alias_text=t.alias_text,
                    normalized_alias=norm_alias,
                    entity_type=t.entity_type,
                    entity_id=t.entity_id,
                    canonical_verify=t.canonical_verify,
                    status="CONFLICT_OTHER_ENTITY",
                ))
                log.warning(
                    "  [CONFLICT_OTHER  ] %-32s alias already points to a DIFFERENT entity — skipping",
                    t.alias_text,
                )
                continue

            # Clean: alias does not exist yet
            results.append(AliasResult(
                alias_text=t.alias_text,
                normalized_alias=norm_alias,
                entity_type=t.entity_type,
                entity_id=t.entity_id,
                canonical_verify=t.canonical_verify,
                status="WOULD_INSERT",
            ))
            log.info(
                "  [WOULD_INSERT    ] %-32s -> %s (id=%d)  norm='%s'",
                t.alias_text, detail, t.entity_id, norm_alias,
            )

        # ── Phase 2: Write pass (--apply only) ────────────────────────────
        db_writes = 0
        if apply:
            to_insert = [r for r in results if r.status == "WOULD_INSERT"]
            log.info("Phase 2 — Writing %d rows to resolver_aliases (match_type=%s)", len(to_insert), MATCH_TYPE)
            for r in to_insert:
                cur.execute(
                    """
                    INSERT INTO resolver_aliases
                        (alias_text, normalized_alias_text, entity_type,
                         entity_id, match_type, confidence)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (normalized_alias_text, entity_type, entity_id)
                    DO NOTHING
                    """,
                    (r.alias_text, r.normalized_alias, r.entity_type,
                     r.entity_id, MATCH_TYPE, CONFIDENCE),
                )
                r.status = "INSERTED"
                db_writes += 1
            conn.commit()
            log.info("Phase 2 — %d rows committed.", db_writes)
        else:
            conn.rollback()   # explicit: no writes were made
            log.info("Phase 2 — SKIPPED (dry-run mode).")

    finally:
        conn.close()

    # ── Summary ───────────────────────────────────────────────────────────
    n_total    = len(results)
    n_found    = sum(1 for r in results if r.status not in ("MISSING_TARGET", "VERIFY_MISMATCH"))
    n_missing  = sum(1 for r in results if r.status == "MISSING_TARGET")
    n_mismatch = sum(1 for r in results if r.status == "VERIFY_MISMATCH")
    n_conflict = sum(1 for r in results if r.status == "CONFLICT_OTHER_ENTITY")
    n_existing = sum(1 for r in results if r.status == "EXISTING")
    n_would    = sum(1 for r in results if r.status == "WOULD_INSERT")
    n_inserted = sum(1 for r in results if r.status == "INSERTED")
    n_skipped  = n_missing + n_mismatch + n_conflict + n_existing

    sep = "=" * 66
    print()
    print(sep)
    print(f"Phase G4 Alias Seed — {'** DRY RUN ** (no DB writes)' if not apply else 'APPLIED'}")
    print(sep)
    print(f"  Total targets          : {n_total}")
    print(f"  Found in KB            : {n_found}")
    print(f"  MISSING_TARGET  (skip) : {n_missing}")
    print(f"  VERIFY_MISMATCH (skip) : {n_mismatch}")
    print(f"  CONFLICT_OTHER  (skip) : {n_conflict}")
    print(f"  Already existing (skip): {n_existing}")
    print(f"  Would insert           : {n_would}")
    print(f"  Inserted               : {n_inserted}")
    print(f"  Skipped (total)        : {n_skipped}")
    print(f"  DB writes              : {'YES — ' + str(n_inserted) + ' rows committed' if n_inserted else '0 (none)'}")
    print(sep)

    if n_conflict:
        print("\nCONFLICT_OTHER_ENTITY (alias already points to a different entity — manual review required):")
        for r in results:
            if r.status == "CONFLICT_OTHER_ENTITY":
                print(f"  CONFLICT  [{r.entity_type:7s}] '{r.alias_text}'  norm='{r.normalized_alias}'  intended_id={r.entity_id}")

    if n_missing:
        print("\nMISSING_TARGET (entity_id not found in resolver KB):")
        for r in results:
            if r.status == "MISSING_TARGET":
                print(f"  MISSING   [{r.entity_type:7s}] id={r.entity_id}  verify='{r.canonical_verify}'")

    print(f"\nWould-insert / Inserted rows ({n_would + n_inserted} total):")
    for r in results:
        if r.status in ("WOULD_INSERT", "INSERTED"):
            print(
                f"  {r.status:12s}  [{r.entity_type:7s}]  "
                f"alias='{r.alias_text}'  "
                f"norm='{r.normalized_alias}'  "
                f"entity_id={r.entity_id}  "
                f"match_type='{MATCH_TYPE}'"
            )

    if not apply:
        print()
        print("Dry-run complete — zero DB writes performed.")
        print()
        print("To apply (Railway):")
        print("  railway run --service pipeline-daily -- python3 scripts/seed_g4_aliases.py --apply")
        print()
        print("To apply (local with public DB URL):")
        print("  DATABASE_URL=<prod-public-url> python3 scripts/seed_g4_aliases.py --apply")
        print()
        print("Rollback command (after --apply, if needed):")
        print("  DELETE FROM resolver_aliases WHERE match_type = 'g4_seed';")

    if n_missing == n_total:
        log.error(
            "All %d targets MISSING — verify DATABASE_URL and resolver table state.", n_total
        )
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Phase G4 Batch 1: Seed 4 approved aliases into resolver_aliases. "
            "Default is DRY-RUN (read-only, zero DB writes). "
            "Pass --apply to write."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help=(
            "Write aliases to resolver_aliases. "
            "Without this flag the script is read-only."
        ),
    )
    args = parser.parse_args()

    if args.apply:
        log.warning("--apply flag set: will write to resolver_aliases (match_type='%s').", MATCH_TYPE)
    else:
        log.info("Dry-run mode (default): no DB writes will occur.")

    run(apply=args.apply)
