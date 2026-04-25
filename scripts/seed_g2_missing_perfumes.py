#!/usr/bin/env python3
"""
scripts/seed_g2_missing_perfumes.py — Phase G2.1 Missing Perfume Entity Seed

Seeds resolver KB with high-value perfume entities that were absent from the
Parfumo/Kaggle Phase 5 import and are needed for G1 Arabic/ME query resolution.

Two operation types:
  CREATE   — insert new entity into resolver_perfumes + resolver_fragrance_master
             + aliases. Used when the canonical perfume does not exist at all.
  ALIAS_TO_EXISTING — insert alias rows only, pointing to an already-existing
             resolver_perfumes.id. Used when the entity exists under a different
             name or brand split (e.g. Angels' Share under Kilian vs. By Kilian).

Default mode: DRY-RUN (zero DB writes). Pass --apply to execute.

Source tagging (for rollback):
  - resolver_fragrance_master.source = 'g2_entity_seed'   (CREATE rows only)
  - resolver_aliases.match_type      = 'g2_entity_seed'   (all alias rows)

Idempotent: ON CONFLICT DO NOTHING everywhere — safe to re-run.

──────────────────────────────────────────────────────────────────────────────
ROLLBACK (if needed after --apply):
    BEGIN;
    DELETE FROM resolver_aliases WHERE match_type = 'g2_entity_seed';
    DELETE FROM resolver_perfumes
      WHERE id IN (
        SELECT perfume_id FROM resolver_fragrance_master
        WHERE source = 'g2_entity_seed' AND perfume_id IS NOT NULL
      );
    DELETE FROM resolver_fragrance_master WHERE source = 'g2_entity_seed';
    COMMIT;
──────────────────────────────────────────────────────────────────────────────

Batch 1 (--batch 1, default):
  CREATE:
    - Lattafa Oud Mood   (brand_id=9,   aliases: oud mood / lattafa oud mood)
    - Lattafa Yara       (brand_id=9,   aliases: yara / lattafa yara)
    - Ajmal Evoke        (brand_id=308, aliases: ajmal evoke)
  ALIAS_TO_EXISTING:
    - Angels' Share      (→ existing resolver_perfumes.id=9119 [Kilian brand],
                           aliases: angels share / kilian angels share)
    - Initio Side Effect (→ existing resolver_perfumes.id=50629,
                           aliases: initio side effect)
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
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
# Normalization — mirrors alias_generator.normalize_text exactly
# ---------------------------------------------------------------------------

def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).lower().strip()
    text = re.sub(r"'s\b", "", text)        # amouage's → amouage
    text = re.sub(r"'", " ", text)          # d'hermes → d hermes
    text = re.sub(r"[^\w\s]+", " ", text)   # strip remaining punctuation
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Target definitions
# ---------------------------------------------------------------------------

@dataclass
class CreateTarget:
    """Create a new resolver entity + aliases."""
    brand_name: str           # display brand, e.g. "Lattafa"
    perfume_name: str         # display perfume, e.g. "Oud Mood"
    brand_id: int             # verified resolver_brands.id
    alias_texts: list[str]    # display alias texts (will be normalized)
    fragrance_id: str         # unique text key for resolver_fragrance_master
    batch: int = 1

    @property
    def canonical_name(self) -> str:
        return f"{self.brand_name} {self.perfume_name}"

    @property
    def normalized_name(self) -> str:
        return _normalize(self.canonical_name)


@dataclass
class AliasToExistingTarget:
    """Add aliases pointing to an already-existing resolver_perfumes row."""
    description: str          # human label for logging
    existing_entity_id: int   # resolver_perfumes.id (verified)
    alias_texts: list[str]    # display alias texts (will be normalized)
    batch: int = 1


# ---------------------------------------------------------------------------
# Batch 1 data
# ---------------------------------------------------------------------------

BATCH_1_CREATES: list[CreateTarget] = [
    CreateTarget(
        brand_name="Lattafa",
        perfume_name="Oud Mood",
        brand_id=9,
        alias_texts=["oud mood", "lattafa oud mood"],
        fragrance_id="g2e_lattafa_oud_mood",
    ),
    CreateTarget(
        brand_name="Lattafa",
        perfume_name="Yara",
        brand_id=9,
        alias_texts=["yara", "lattafa yara"],
        fragrance_id="g2e_lattafa_yara",
    ),
    CreateTarget(
        brand_name="Ajmal",
        perfume_name="Evoke",
        brand_id=308,
        alias_texts=["ajmal evoke"],
        fragrance_id="g2e_ajmal_evoke",
    ),
]

BATCH_1_ALIAS_TO_EXISTING: list[AliasToExistingTarget] = [
    AliasToExistingTarget(
        description="Angels' Share (Kilian id=9119)",
        existing_entity_id=9119,
        alias_texts=["angels share", "kilian angels share"],
        # Note: Angels' Share canonical is stored under Kilian (brand_id=670),
        # NOT under By Kilian (brand_id=158). Do NOT create a new entity here.
    ),
    AliasToExistingTarget(
        description="Initio Side Effect (id=50629)",
        existing_entity_id=50629,
        alias_texts=["initio side effect"],
    ),
]

ALL_BATCHES: dict[int, tuple[list[CreateTarget], list[AliasToExistingTarget]]] = {
    1: (BATCH_1_CREATES, BATCH_1_ALIAS_TO_EXISTING),
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class CreateResult:
    target: CreateTarget
    # Pre-flight checks
    brand_found: bool = False
    perfume_already_exists: bool = False
    fm_already_exists: bool = False
    existing_perfume_id: Optional[int] = None
    # Alias statuses: list of (alias_text, normalized, status)
    alias_results: list[tuple[str, str, str]] = field(default_factory=list)
    # Overall status
    status: str = "PENDING"   # WOULD_CREATE | EXISTS | MISSING_BRAND | APPLIED | ERROR
    new_perfume_id: Optional[int] = None


@dataclass
class AliasToExistingResult:
    target: AliasToExistingTarget
    entity_exists: bool = False
    alias_results: list[tuple[str, str, str]] = field(default_factory=list)
    status: str = "PENDING"   # WOULD_ALIAS | MISSING_ENTITY | APPLIED | ERROR


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_connection():
    import psycopg2
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        log.error(
            "DATABASE_URL is not set.\n"
            "  DATABASE_URL=postgresql://... python3 scripts/seed_g2_missing_perfumes.py"
        )
        sys.exit(1)
    if database_url.startswith("sqlite"):
        log.error("This script requires PostgreSQL. DATABASE_URL points to SQLite.")
        sys.exit(1)
    if database_url.startswith("postgresql+psycopg2://"):
        database_url = database_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    host = database_url.split("@")[-1] if "@" in database_url else database_url
    log.info("Connecting to Postgres at ...%s", host)
    return psycopg2.connect(database_url)


def _brand_exists(cur, brand_id: int) -> bool:
    cur.execute("SELECT 1 FROM resolver_brands WHERE id = %s LIMIT 1", (brand_id,))
    return cur.fetchone() is not None


def _perfume_exists(cur, normalized_name: str) -> Optional[int]:
    """Return resolver_perfumes.id if the normalized_name already exists, else None."""
    cur.execute(
        "SELECT id FROM resolver_perfumes WHERE normalized_name = %s LIMIT 1",
        (normalized_name,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _fm_exists(cur, normalized_name: str) -> bool:
    cur.execute(
        "SELECT 1 FROM resolver_fragrance_master WHERE normalized_name = %s LIMIT 1",
        (normalized_name,),
    )
    return cur.fetchone() is not None


def _fm_fragrance_id_exists(cur, fragrance_id: str) -> bool:
    cur.execute(
        "SELECT 1 FROM resolver_fragrance_master WHERE fragrance_id = %s LIMIT 1",
        (fragrance_id,),
    )
    return cur.fetchone() is not None


def _alias_exists(cur, normalized_alias: str, entity_type: str, entity_id: int) -> bool:
    cur.execute(
        "SELECT 1 FROM resolver_aliases "
        "WHERE normalized_alias_text = %s AND entity_type = %s AND entity_id = %s LIMIT 1",
        (normalized_alias, entity_type, entity_id),
    )
    return cur.fetchone() is not None


def _entity_exists(cur, entity_id: int) -> bool:
    cur.execute("SELECT 1 FROM resolver_perfumes WHERE id = %s LIMIT 1", (entity_id,))
    return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Audit phases
# ---------------------------------------------------------------------------

def _audit_create(cur, target: CreateTarget) -> CreateResult:
    result = CreateResult(target=target)

    # 1. Brand check
    result.brand_found = _brand_exists(cur, target.brand_id)
    if not result.brand_found:
        result.status = "MISSING_BRAND"
        log.warning(
            "  [MISSING_BRAND] %-30s brand_id=%d not found in resolver_brands",
            target.canonical_name, target.brand_id,
        )
        return result

    # 2. Perfume duplicate check (resolver_perfumes)
    existing_id = _perfume_exists(cur, target.normalized_name)
    if existing_id is not None:
        result.perfume_already_exists = True
        result.existing_perfume_id = existing_id
        result.status = "EXISTS"
        log.info(
            "  [EXISTS        ] %-30s already in resolver_perfumes (id=%d)",
            target.canonical_name, existing_id,
        )
        return result

    # 3. FM duplicate check
    result.fm_already_exists = _fm_fragrance_id_exists(cur, target.fragrance_id) or \
                                _fm_exists(cur, target.normalized_name)
    if result.fm_already_exists:
        result.status = "EXISTS"
        log.info(
            "  [EXISTS_FM     ] %-30s already in resolver_fragrance_master",
            target.canonical_name,
        )
        return result

    # 4. Alias pre-flight (will point to whichever id gets created)
    #    We can only check for alias conflicts after we know the target entity_id.
    #    For dry-run we just report WOULD_INSERT for all aliases since entity is new.
    for alias_text in target.alias_texts:
        norm = _normalize(alias_text)
        result.alias_results.append((alias_text, norm, "WOULD_INSERT"))

    result.status = "WOULD_CREATE"
    log.info(
        "  [WOULD_CREATE  ] %-30s brand_id=%d  aliases=%s",
        target.canonical_name, target.brand_id,
        ", ".join(repr(a) for a in target.alias_texts),
    )
    return result


def _audit_alias_to_existing(cur, target: AliasToExistingTarget) -> AliasToExistingResult:
    result = AliasToExistingResult(target=target)

    # 1. Verify the entity exists
    result.entity_exists = _entity_exists(cur, target.existing_entity_id)
    if not result.entity_exists:
        result.status = "MISSING_ENTITY"
        log.warning(
            "  [MISSING_ENTITY] %-40s entity_id=%d not found",
            target.description, target.existing_entity_id,
        )
        return result

    # 2. Check each alias
    any_would_insert = False
    for alias_text in target.alias_texts:
        norm = _normalize(alias_text)
        exists = _alias_exists(cur, norm, "perfume", target.existing_entity_id)
        status = "EXISTING" if exists else "WOULD_INSERT"
        if not exists:
            any_would_insert = True
        result.alias_results.append((alias_text, norm, status))
        log.info(
            "  [%-13s] %-30s alias=%r → entity_id=%d",
            status, target.description, alias_text, target.existing_entity_id,
        )

    result.status = "WOULD_ALIAS" if any_would_insert else "EXISTS"
    return result


# ---------------------------------------------------------------------------
# Write phases
# ---------------------------------------------------------------------------

def _apply_create(cur, target: CreateTarget, result: CreateResult) -> None:
    """Insert resolver_perfumes → resolver_fragrance_master → resolver_aliases atomically."""
    # 1. resolver_perfumes
    cur.execute(
        """
        INSERT INTO resolver_perfumes (canonical_name, normalized_name, brand_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (normalized_name) DO NOTHING
        RETURNING id
        """,
        (target.canonical_name, target.normalized_name, target.brand_id),
    )
    row = cur.fetchone()
    if row is None:
        # ON CONFLICT — perfume was inserted between audit and apply (race), or name exists
        existing_id = _perfume_exists(cur, target.normalized_name)
        result.new_perfume_id = existing_id
        log.warning(
            "  [CONFLICT      ] resolver_perfumes %s — using existing id=%s",
            target.canonical_name, existing_id,
        )
    else:
        result.new_perfume_id = row[0]
        log.info(
            "  [INSERTED      ] resolver_perfumes %s id=%d",
            target.canonical_name, result.new_perfume_id,
        )

    if result.new_perfume_id is None:
        log.error("  Cannot proceed — no perfume_id for %s", target.canonical_name)
        return

    # 2. resolver_fragrance_master
    cur.execute(
        """
        INSERT INTO resolver_fragrance_master
            (fragrance_id, brand_name, perfume_name, canonical_name,
             normalized_name, source, brand_id, perfume_id)
        VALUES (%s, %s, %s, %s, %s, 'g2_entity_seed', %s, %s)
        ON CONFLICT (fragrance_id) DO NOTHING
        """,
        (
            target.fragrance_id,
            target.brand_name,
            target.perfume_name,
            target.canonical_name,
            target.normalized_name,
            target.brand_id,
            result.new_perfume_id,
        ),
    )

    # 3. resolver_aliases
    for alias_text, norm_alias, _ in result.alias_results:
        cur.execute(
            """
            INSERT INTO resolver_aliases
                (alias_text, normalized_alias_text, entity_type,
                 entity_id, match_type, confidence)
            VALUES (%s, %s, 'perfume', %s, 'g2_entity_seed', 0.90)
            ON CONFLICT (normalized_alias_text, entity_type, entity_id) DO NOTHING
            """,
            (alias_text, norm_alias, result.new_perfume_id),
        )
        log.info(
            "  [ALIAS_INSERTED] %r → %s (id=%d)",
            alias_text, target.canonical_name, result.new_perfume_id,
        )

    result.status = "APPLIED"


def _apply_alias_to_existing(cur, target: AliasToExistingTarget,
                              result: AliasToExistingResult) -> None:
    for alias_text, norm_alias, prior_status in result.alias_results:
        if prior_status == "EXISTING":
            log.info("  [SKIP_EXISTING ] alias=%r already exists", alias_text)
            continue
        cur.execute(
            """
            INSERT INTO resolver_aliases
                (alias_text, normalized_alias_text, entity_type,
                 entity_id, match_type, confidence)
            VALUES (%s, %s, 'perfume', %s, 'g2_entity_seed', 0.90)
            ON CONFLICT (normalized_alias_text, entity_type, entity_id) DO NOTHING
            """,
            (alias_text, norm_alias, target.existing_entity_id),
        )
        log.info(
            "  [ALIAS_INSERTED] %r → entity_id=%d",
            alias_text, target.existing_entity_id,
        )
    result.status = "APPLIED"


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run(batch: int, apply: bool) -> None:
    if batch not in ALL_BATCHES:
        log.error("Unknown batch %d. Available: %s", batch, sorted(ALL_BATCHES))
        sys.exit(1)

    creates, alias_to_existing = ALL_BATCHES[batch]
    conn = _get_connection()
    create_results: list[CreateResult] = []
    alias_results: list[AliasToExistingResult] = []

    try:
        cur = conn.cursor()

        # ── Phase 1: Read-only audit ──────────────────────────────────────
        log.info(
            "Phase 1 — Audit  batch=%d  creates=%d  alias_to_existing=%d  dry_run=%s",
            batch, len(creates), len(alias_to_existing), not apply,
        )

        log.info("── CREATE targets ──")
        for t in creates:
            create_results.append(_audit_create(cur, t))

        log.info("── ALIAS_TO_EXISTING targets ──")
        for t in alias_to_existing:
            alias_results.append(_audit_alias_to_existing(cur, t))

        # ── Phase 2: Write pass (--apply only) ────────────────────────────
        if apply:
            log.warning("Phase 2 — Writing (--apply is active)")
            for r in create_results:
                if r.status == "WOULD_CREATE":
                    log.info("  → CREATE %s", r.target.canonical_name)
                    _apply_create(cur, r.target, r)
                else:
                    log.info("  → SKIP   %s  [%s]", r.target.canonical_name, r.status)

            for r in alias_results:
                if r.status == "WOULD_ALIAS":
                    log.info("  → ALIAS  %s", r.target.description)
                    _apply_alias_to_existing(cur, r.target, r)
                else:
                    log.info("  → SKIP   %s  [%s]", r.target.description, r.status)

            conn.commit()
            log.info("Phase 2 — committed.")
        else:
            conn.rollback()
            log.info("Phase 2 — SKIPPED (dry-run mode).")

    finally:
        conn.close()

    # ── Summary ──────────────────────────────────────────────────────────
    n_would_create       = sum(1 for r in create_results if r.status in ("WOULD_CREATE", "APPLIED"))
    n_create_exists      = sum(1 for r in create_results if r.status == "EXISTS")
    n_create_missing_br  = sum(1 for r in create_results if r.status == "MISSING_BRAND")
    n_would_alias        = sum(1 for r in alias_results if r.status in ("WOULD_ALIAS", "APPLIED"))
    n_alias_exists       = sum(1 for r in alias_results if r.status == "EXISTS")
    n_alias_missing      = sum(1 for r in alias_results if r.status == "MISSING_ENTITY")

    # Count alias rows
    would_insert_aliases = sum(
        sum(1 for _, _, s in r.alias_results if s == "WOULD_INSERT")
        for r in create_results if r.status in ("WOULD_CREATE", "APPLIED")
    )
    would_insert_aliases += sum(
        sum(1 for _, _, s in r.alias_results if s == "WOULD_INSERT")
        for r in alias_results if r.status in ("WOULD_ALIAS", "APPLIED")
    )
    existing_aliases = sum(
        sum(1 for _, _, s in r.alias_results if s == "EXISTING")
        for r in alias_results
    )

    n_applied = sum(1 for r in create_results if r.status == "APPLIED") + \
                sum(1 for r in alias_results if r.status == "APPLIED")

    sep = "=" * 70
    print()
    print(sep)
    print(f"Phase G2.1 Batch {batch} — {'** DRY RUN ** (no writes)' if not apply else 'APPLIED'}")
    print(sep)
    print(f"  CREATE targets            : {len(creates)}")
    print(f"    would_create            : {n_would_create}")
    print(f"    already_exists          : {n_create_exists}")
    print(f"    missing_brand           : {n_create_missing_br}")
    print(f"  ALIAS_TO_EXISTING targets : {len(alias_to_existing)}")
    print(f"    would_alias             : {n_would_alias}")
    print(f"    all_aliases_exist       : {n_alias_exists}")
    print(f"    missing_entity          : {n_alias_missing}")
    print(f"  ─────────────────────────────────────────────────────────")
    print(f"  Alias rows would_insert   : {would_insert_aliases}")
    print(f"  Alias rows already_exist  : {existing_aliases}")
    print(f"  DB writes                 : {'YES — ' + str(n_applied) + ' targets applied' if apply else 'NO'}")
    print(sep)

    # Detail tables
    print("\nCREATE targets:")
    for r in create_results:
        marker = "WOULD_CREATE" if r.status in ("WOULD_CREATE", "APPLIED") else r.status
        print(f"  [{marker:15s}] {r.target.canonical_name!r:35s}  brand_id={r.target.brand_id}")
        for alias_text, norm, alias_status in r.alias_results:
            print(f"      alias {alias_status:12s}  {alias_text!r:25s} → {norm!r}")

    print("\nALIAS_TO_EXISTING targets:")
    for r in alias_results:
        print(f"  [{r.status:15s}] {r.target.description}")
        for alias_text, norm, alias_status in r.alias_results:
            print(f"      alias {alias_status:12s}  {alias_text!r:25s} → entity_id={r.target.existing_entity_id}")

    if not apply:
        print()
        print("Dry-run complete — zero DB writes performed.")
        print(
            f"To apply: DATABASE_URL=... python3 scripts/seed_g2_missing_perfumes.py "
            f"--batch {batch} --apply"
        )
        print()
        print("Rollback SQL (run after --apply if needed):")
        print("  BEGIN;")
        print("  DELETE FROM resolver_aliases WHERE match_type = 'g2_entity_seed';")
        print("  DELETE FROM resolver_perfumes")
        print("    WHERE id IN (")
        print("      SELECT perfume_id FROM resolver_fragrance_master")
        print("      WHERE source = 'g2_entity_seed' AND perfume_id IS NOT NULL")
        print("    );")
        print("  DELETE FROM resolver_fragrance_master WHERE source = 'g2_entity_seed';")
        print("  COMMIT;")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Phase G2.1: Seed missing high-value perfume entities into the resolver KB. "
            "Default is DRY-RUN. Pass --apply to write."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Rollback after --apply:
  BEGIN;
  DELETE FROM resolver_aliases WHERE match_type = 'g2_entity_seed';
  DELETE FROM resolver_perfumes
    WHERE id IN (
      SELECT perfume_id FROM resolver_fragrance_master
      WHERE source = 'g2_entity_seed' AND perfume_id IS NOT NULL
    );
  DELETE FROM resolver_fragrance_master WHERE source = 'g2_entity_seed';
  COMMIT;
""",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Execute DB writes. Without this flag: dry-run only.",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=1,
        help="Which batch to run (default: 1). Currently only batch 1 is implemented.",
    )
    args = parser.parse_args()

    if args.apply:
        log.warning("--apply flag active: will write to resolver KB.")
    else:
        log.info("Dry-run mode (default): no DB writes will occur.")

    run(batch=args.batch, apply=args.apply)
