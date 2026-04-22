from __future__ import annotations

"""Phase 4P — Postgres-backed promotion execution layer.

Mirrors the execution interface of promoter.py but writes to Postgres
resolver_* tables (migration 014) instead of SQLite.

  KB reads/writes  : PgResolverStore._engine → resolver_* Postgres tables
  Market DB writes : SQLAlchemy Session → fragrance_candidates in Postgres

All read-only logic (safeguard_check, check_exact, check_merge, resolve_brand,
precheck_candidate, run_prechecks) is re-exported unchanged from promoter.py —
those functions only examine in-memory snapshots and never touch a DB connection.

PRODUCTION GUARD
----------------
If PTI_ENV=production and DATABASE_URL is not set, PgResolverStore.__init__()
will raise RuntimeError via get_engine() before any work is done.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from perfume_trend_sdk.storage.entities.pg_resolver_store import PgResolverStore

# Re-export pure read-only logic — no DB interaction in these functions
from .promoter import (  # noqa: F401
    DECISION_CREATE,
    DECISION_EXACT,
    DECISION_MERGE,
    DECISION_REJECT,
    PromotionCheck,
    _now_iso,
    check_exact,
    check_merge,
    get_promotion_text,
    precheck_candidate,
    resolve_brand,
    run_prechecks,
    safeguard_check,
)

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# KB snapshot — reads from resolver_* Postgres tables
# ---------------------------------------------------------------------------

def load_kb_snapshot_pg(store: PgResolverStore) -> Dict[str, Any]:
    """Load resolver Postgres tables into memory for fast in-process lookups.

    Returns the same dict shape as promoter.load_kb_snapshot() so that all
    precheck logic (check_exact, check_merge, resolve_brand) works unchanged.

    Extra key added:
      perfume_id_canon  — {resolver_perfume_id: canonical_name}
                          Alias of 'perfume_canon'; keeps review_create_bucket
                          compatibility without any code change there.
    """
    with store._engine.connect() as conn:
        alias_rows = conn.execute(text(
            "SELECT normalized_alias_text, entity_id, entity_type "
            "FROM resolver_aliases"
        )).fetchall()

        perfume_rows = conn.execute(text(
            "SELECT id, canonical_name FROM resolver_perfumes"
        )).fetchall()

        brand_rows = conn.execute(text(
            "SELECT id, canonical_name, normalized_name "
            "FROM resolver_brands WHERE normalized_name IS NOT NULL"
        )).fetchall()

        fm_rows = conn.execute(text(
            "SELECT fragrance_id, canonical_name, normalized_name, perfume_id "
            "FROM resolver_fragrance_master WHERE normalized_name IS NOT NULL"
        )).fetchall()

    perfume_canon: Dict[int, str] = {int(r[0]): str(r[1]) for r in perfume_rows}
    brand_canon: Dict[int, str] = {}
    brand_lookup: Dict[str, Tuple] = {}

    for r in brand_rows:
        bid, bcanon, bnorm = int(r[0]), str(r[1]), str(r[2])
        brand_canon[bid] = bcanon
        brand_lookup[bnorm] = (bid, bcanon)

    alias_lookup: Dict[str, Tuple] = {}
    brand_alias_lookup: Dict[str, Tuple] = {}
    for r in alias_rows:
        norm_text, entity_id, entity_type = str(r[0]), int(r[1]), str(r[2])
        alias_lookup[norm_text] = (entity_id, entity_type)
        if entity_type == "brand":
            brand_alias_lookup[norm_text] = (entity_id, brand_canon.get(entity_id, ""))

    fm_lookup: Dict[str, Tuple] = {}
    fm_list: List[Tuple] = []
    for r in fm_rows:
        fid, fcanon, fnorm, fpid = str(r[0]), str(r[1]), str(r[2]), r[3]
        fpid_int = int(fpid) if fpid is not None else None
        fm_lookup[fnorm] = (fid, fcanon, fpid_int)
        fm_list.append((fnorm, fid, fcanon, fpid_int))

    return {
        "alias_lookup": alias_lookup,
        "fm_lookup": fm_lookup,
        "brand_lookup": brand_lookup,
        "brand_alias_lookup": brand_alias_lookup,
        "perfume_canon": perfume_canon,
        "brand_canon": brand_canon,
        "fm_list": fm_list,
        # Extra key for review_create_bucket compatibility
        "perfume_id_canon": perfume_canon,
    }


# ---------------------------------------------------------------------------
# Alias existence check — resolver_aliases
# ---------------------------------------------------------------------------

def _alias_exists_pg(
    store: PgResolverStore,
    normalized_text: str,
    entity_id: int,
    entity_type: str,
) -> bool:
    with store._engine.connect() as conn:
        row = conn.execute(text(
            "SELECT id FROM resolver_aliases "
            "WHERE normalized_alias_text = :norm "
            "  AND entity_id = :eid "
            "  AND entity_type = :etype"
        ), {"norm": normalized_text, "eid": entity_id, "etype": entity_type}).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Execute merge — adds alias to resolver_aliases
# ---------------------------------------------------------------------------

def execute_merge_pg(check: PromotionCheck, store: PgResolverStore) -> str:
    """Add the candidate as a new alias in resolver_aliases.

    Returns the alias_text that was inserted, or 'already_exists' if the
    normalized/entity_id/entity_type triple is already present.
    """
    entity_id = check.matched_entity_id
    entity_type = "perfume"   # merge is always perfume in Phase 4b/4c v1
    norm_text = check.promotion_text
    alias_text = " ".join(t.capitalize() for t in norm_text.split())

    if _alias_exists_pg(store, norm_text, entity_id, entity_type):
        return "already_exists"

    with store._engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO resolver_aliases "
            "  (alias_text, normalized_alias_text, entity_type, entity_id, "
            "   match_type, confidence) "
            "VALUES (:alias_text, :norm, :etype, :eid, 'discovery_generated', 0.85) "
            "ON CONFLICT ON CONSTRAINT uq_resolver_aliases_lookup DO NOTHING"
        ), {
            "alias_text": alias_text,
            "norm": norm_text,
            "etype": entity_type,
            "eid": entity_id,
        })
    return alias_text


# ---------------------------------------------------------------------------
# Execute merge using raw alias parameters (used in review_create_bucket inline paths)
# ---------------------------------------------------------------------------

def insert_alias_pg(
    store: PgResolverStore,
    *,
    alias_text: str,
    normalized_alias_text: str,
    entity_type: str,
    entity_id: int,
    match_type: str = "discovery_generated",
    confidence: float = 0.85,
) -> str:
    """Insert a single alias into resolver_aliases; idempotent via ON CONFLICT.

    Returns 'inserted' or 'already_exists'.
    """
    if _alias_exists_pg(store, normalized_alias_text, entity_id, entity_type):
        return "already_exists"
    with store._engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO resolver_aliases "
            "  (alias_text, normalized_alias_text, entity_type, entity_id, "
            "   match_type, confidence) "
            "VALUES (:alias_text, :norm, :etype, :eid, :match_type, :confidence) "
            "ON CONFLICT ON CONSTRAINT uq_resolver_aliases_lookup DO NOTHING"
        ), {
            "alias_text": alias_text,
            "norm": normalized_alias_text,
            "etype": entity_type,
            "eid": entity_id,
            "match_type": match_type,
            "confidence": confidence,
        })
    return "inserted"


# ---------------------------------------------------------------------------
# Execute create perfume — resolver_perfumes + resolver_fragrance_master + aliases
# ---------------------------------------------------------------------------

def execute_create_perfume_pg(
    check: PromotionCheck,
    store: PgResolverStore,
    candidate_id: int,
) -> Tuple[int, str]:
    """Create a new perfume in the Postgres resolver KB.

    Steps (atomic transaction):
    1. INSERT INTO resolver_perfumes → get new integer id
    2. INSERT INTO resolver_fragrance_master with source='discovery'
    3. INSERT primary alias (canonical_name → new id)
    4. INSERT original promotion_text alias if different from canonical

    Returns (new_perfume_id, canonical_name).
    """
    brand_id = check.brand_id
    canonical_name = check.canonical_name_to_create
    normalized_name = check.normalized_name_to_create
    brand_name = check.brand_name
    perfume_name = canonical_name.replace(brand_name, "").strip() if brand_name else canonical_name
    fragrance_id = f"disc_{candidate_id:06d}"

    with store._engine.begin() as conn:
        # 1. Perfume row
        row = conn.execute(text(
            "INSERT INTO resolver_perfumes "
            "  (brand_id, canonical_name, normalized_name) "
            "VALUES (:brand_id, :canonical, :normalized) "
            "ON CONFLICT (normalized_name) DO UPDATE "
            "  SET canonical_name = EXCLUDED.canonical_name "
            "RETURNING id"
        ), {
            "brand_id": brand_id,
            "canonical": canonical_name,
            "normalized": normalized_name,
        }).fetchone()
        new_perfume_id = int(row[0])

        # 2. Fragrance master row
        conn.execute(text(
            "INSERT INTO resolver_fragrance_master "
            "  (fragrance_id, brand_name, perfume_name, canonical_name, "
            "   normalized_name, source, brand_id, perfume_id) "
            "VALUES (:fid, :brand_name, :perf_name, :canonical, :normalized, "
            "        'discovery', :brand_id, :perfume_id) "
            "ON CONFLICT (fragrance_id) DO NOTHING"
        ), {
            "fid": fragrance_id,
            "brand_name": brand_name,
            "perf_name": perfume_name,
            "canonical": canonical_name,
            "normalized": normalized_name,
            "brand_id": brand_id,
            "perfume_id": new_perfume_id,
        })

        # 3. Primary alias (canonical normalized_name → new id)
        conn.execute(text(
            "INSERT INTO resolver_aliases "
            "  (alias_text, normalized_alias_text, entity_type, entity_id, "
            "   match_type, confidence) "
            "VALUES (:alias_text, :norm, 'perfume', :eid, 'discovery_generated', 0.80) "
            "ON CONFLICT ON CONSTRAINT uq_resolver_aliases_lookup DO NOTHING"
        ), {
            "alias_text": canonical_name,
            "norm": normalized_name,
            "eid": new_perfume_id,
        })

        # 4. Original promotion text as alias if different from canonical
        orig_norm = check.promotion_text
        if orig_norm != normalized_name:
            orig_alias_text = " ".join(t.capitalize() for t in orig_norm.split())
            conn.execute(text(
                "INSERT INTO resolver_aliases "
                "  (alias_text, normalized_alias_text, entity_type, entity_id, "
                "   match_type, confidence) "
                "VALUES (:alias_text, :norm, 'perfume', :eid, 'discovery_generated', 0.75) "
                "ON CONFLICT ON CONSTRAINT uq_resolver_aliases_lookup DO NOTHING"
            ), {
                "alias_text": orig_alias_text,
                "norm": orig_norm,
                "eid": new_perfume_id,
            })

    return new_perfume_id, canonical_name


# ---------------------------------------------------------------------------
# Execute create brand — resolver_brands + alias
# ---------------------------------------------------------------------------

def execute_create_brand_pg(
    check: PromotionCheck,
    store: PgResolverStore,
) -> Tuple[int, str]:
    """Create a new brand in the Postgres resolver KB.

    Returns (new_brand_id, canonical_name).
    """
    canonical_name = check.canonical_name_to_create
    normalized_name = check.normalized_name_to_create

    with store._engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO resolver_brands (canonical_name, normalized_name) "
            "VALUES (:canonical, :normalized) "
            "ON CONFLICT (normalized_name) DO UPDATE "
            "  SET canonical_name = EXCLUDED.canonical_name "
            "RETURNING id"
        ), {
            "canonical": canonical_name,
            "normalized": normalized_name,
        }).fetchone()
        new_brand_id = int(row[0])

        conn.execute(text(
            "INSERT INTO resolver_aliases "
            "  (alias_text, normalized_alias_text, entity_type, entity_id, "
            "   match_type, confidence) "
            "VALUES (:alias_text, :norm, 'brand', :eid, 'discovery_generated', 0.80) "
            "ON CONFLICT ON CONSTRAINT uq_resolver_aliases_lookup DO NOTHING"
        ), {
            "alias_text": canonical_name,
            "norm": normalized_name,
            "eid": new_brand_id,
        })

    return new_brand_id, canonical_name


# ---------------------------------------------------------------------------
# Record promotion outcome — writes to fragrance_candidates via market DB session
# ---------------------------------------------------------------------------

def record_promotion_outcome_pg(
    db: Session,
    candidate_id: int,
    decision: str,
    canonical_name: Optional[str],
    promoted_as: Optional[str],
    rejection_reason: Optional[str],
) -> None:
    """Write the promotion decision back to fragrance_candidates in Postgres."""
    db.execute(text(
        "UPDATE fragrance_candidates SET "
        "  promotion_decision           = :decision, "
        "  promoted_at                  = :ts, "
        "  promoted_canonical_name      = :canonical, "
        "  promoted_as                  = :promoted_as, "
        "  promotion_rejection_reason   = :rejection "
        "WHERE id = :id"
    ), {
        "decision": decision,
        "ts": _now_iso(),
        "canonical": canonical_name,
        "promoted_as": promoted_as,
        "rejection": rejection_reason,
        "id": candidate_id,
    })


# ---------------------------------------------------------------------------
# Resolver KB row counts — used for before/after reporting
# ---------------------------------------------------------------------------

def kb_counts_pg(store: PgResolverStore) -> Dict[str, int]:
    """Return row counts for all resolver_* tables."""
    tables = {
        "resolver_fragrance_master": "fragrance_master",
        "resolver_aliases": "aliases",
        "resolver_brands": "brands",
        "resolver_perfumes": "perfumes",
    }
    counts: Dict[str, int] = {}
    with store._engine.connect() as conn:
        for pg_table, label in tables.items():
            row = conn.execute(text(f"SELECT COUNT(*) FROM {pg_table}")).fetchone()  # noqa: S608
            counts[label] = int(row[0])
        # Discovery-specific counts
        row = conn.execute(text(
            "SELECT COUNT(*) FROM resolver_fragrance_master WHERE source = 'discovery'"
        )).fetchone()
        counts["discovery_fm"] = int(row[0])
        row = conn.execute(text(
            "SELECT COUNT(*) FROM resolver_aliases WHERE match_type = 'discovery_generated'"
        )).fetchone()
        counts["discovery_aliases"] = int(row[0])
    return counts


def print_kb_counts_pg(store: PgResolverStore, label: str = "") -> None:
    counts = kb_counts_pg(store)
    if label:
        print(f"\n  [{label}] Resolver KB row counts (Postgres):")
    else:
        print("\n  Resolver KB row counts (Postgres):")
    print(f"    {'fragrance_master':20s}: {counts['fragrance_master']:,}")
    print(f"    {'aliases':20s}: {counts['aliases']:,}")
    print(f"    {'brands':20s}: {counts['brands']:,}")
    print(f"    {'perfumes':20s}: {counts['perfumes']:,}")
    print(f"    discovery FM rows          : {counts['discovery_fm']}")
    print(f"    discovery_generated aliases: {counts['discovery_aliases']}")
