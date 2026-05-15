"""FTG-4 / RI1-E1 — Existing Canonical Relationship Evidence Attachment v1.

Attaches cross_query_retrieval evidence to existing operator-reviewed
fragrance_relationship rows.  Does NOT create new machine-generated relationship
candidates (see Source Semantics note below).

Source semantics:
  entity_topic_links WHERE topic_type='query' stores YouTube discovery search
  queries used by the ingestion pipeline — e.g. "creed aventus perfume".
  These are NOT explicit consumer comparison queries ("creed aventus vs armaf").

  The signal this source actually encodes is cross-query co-retrieval:
    Entity B appears in YouTube content retrieved by a discovery query for Entity A.

  This is a WEAK signal — weaker than explicit VS/dupe comparison phrases.
  It can be real (CDNIM videos appear in Aventus searches because of the dupe
  relationship) or noisy (unrelated niche fragrances surfaced by YouTube's
  algorithm).

Hard gate — no new candidate creation:
  cross_query_retrieval evidence may only be attached to pairs that already exist
  in fragrance_relationships under any relation_type (operator-reviewed seed rows).
  Pairs with no existing relationship are counted under
  candidates_skipped_no_existing_relationship and logged but not persisted.

  Rationale: co-retrieval alone does not justify a new relationship claim.
  New candidate creation requires a pair-level explicit comparison source
  (VS-pattern queries, content body NLP, or operator seed) — none of which
  is currently persisted in production entity_topic_links.

Idempotency rules:
  - relationship_evidence has no DB-level unique constraint, so the harvester
    checks for an existing row with the same
      (relationship_id, evidence_type='cross_query_retrieval', query_text)
    before inserting — preventing duplicate evidence on repeated runs.

Usage:
  python3 scripts/harvest_relationship_evidence.py --dry-run   # preview only
  python3 scripts/harvest_relationship_evidence.py             # write mode
  python3 scripts/harvest_relationship_evidence.py --limit 100 # cap entities processed
  python3 scripts/harvest_relationship_evidence.py --min-occurrences 3  # stricter filter
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections import defaultdict
from datetime import date
from typing import Optional

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from perfume_trend_sdk.db.market.session import get_session_factory
from perfume_trend_sdk.analysis.topic_intelligence.market_intelligence import (
    extract_vs_competitors,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EVIDENCE_TYPE = "cross_query_retrieval"
RELATION_TYPE_DEFAULT = "commonly_compared_to"
FORMULA_VERSION = 1

# Trailing noise suffixes stripped from co-retrieval candidate strings before
# exact-match resolution.  These are descriptor words appended to entity names
# in YouTube discovery search queries (e.g. "creed aventus perfume" →
# "creed aventus").  Stripped only when the raw candidate fails exact match.
_NOISE_SUFFIXES = [
    "eau de parfum",
    "eau de toilette",
    "eau de cologne",
    "edp",
    "edt",
    "parfum",
    "perfume",
    "fragrance",
    "cologne",
    "review",
    "scent",
]

# Minimum cumulative occurrence count for a query pair to generate a candidate.
# Default 2: require the comparison query to have appeared at least twice for
# this entity.  Can be raised with --min-occurrences.
DEFAULT_MIN_OCCURRENCES = 2

# Maximum entities to process in one run (safety cap).
DEFAULT_ENTITY_LIMIT = 500

# Maximum candidate strings to attempt to resolve per entity.
MAX_CANDIDATES_PER_ENTITY = 20


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

def _compute_confidence(occurrence_count: int) -> float:
    """Return machine confidence score for a cross_query_retrieval evidence observation.

    All values are intentionally below the 0.700 public display gate so that
    no machine-generated candidate can ever auto-publish.
    """
    if occurrence_count >= 11:
        return 0.350
    elif occurrence_count >= 6:
        return 0.300
    elif occurrence_count >= 3:
        return 0.250
    else:
        return 0.200


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _fetch_entity_queries(db, min_occurrences: int = 2, limit: int = 500):
    """Return query strings per entity from entity_topic_links.

    Returns a list of dicts:
      {entity_id, canonical_name, query_text, occurrence_count}

    Only includes query rows with occurrence_count >= min_occurrences and
    entities with entity_type='perfume'.
    """
    from sqlalchemy import text
    rows = db.execute(text(
        "SELECT CAST(em.id AS TEXT), em.canonical_name, etl.topic_text, COUNT(*) as occ "
        "FROM entity_market em "
        "JOIN entity_topic_links etl ON etl.entity_id = CAST(em.id AS TEXT) "
        "WHERE em.entity_type = 'perfume' "
        "  AND etl.topic_type = 'query' "
        "GROUP BY CAST(em.id AS TEXT), em.canonical_name, etl.topic_text "
        "HAVING COUNT(*) >= :min_occ "
        "ORDER BY em.canonical_name, COUNT(*) DESC "
        "LIMIT :lim"
    ), {"min_occ": min_occurrences, "lim": limit * MAX_CANDIDATES_PER_ENTITY}).fetchall()
    return [
        {
            "entity_id": r[0],
            "canonical_name": r[1],
            "query_text": r[2],
            "occurrence_count": int(r[3]),
        }
        for r in rows
    ]


def _resolve_candidate(db, candidate_str: str) -> Optional[str]:
    """Try to resolve a raw candidate string to a known entity canonical name.

    Step 1: case-insensitive exact match on entity_market.canonical_name.
    Step 2: if Step 1 fails, strip known noise suffixes (e.g. "perfume",
            "review", "eau de parfum") from the end of the candidate and retry.
            This handles discovery-query strings like "creed aventus perfume"
            which should resolve to "Creed Aventus".

    Returns the canonical_name from entity_market if matched, else None.
    Does NOT use the resolver alias table (v1 is conservative).
    """
    from sqlalchemy import text

    def _query(cand: str) -> Optional[str]:
        row = db.execute(text(
            "SELECT canonical_name FROM entity_market "
            "WHERE entity_type = 'perfume' "
            "  AND LOWER(canonical_name) = LOWER(:cand) "
            "LIMIT 1"
        ), {"cand": cand}).fetchone()
        return row[0] if row else None

    # Step 1: raw exact match
    raw = candidate_str.strip()
    result = _query(raw)
    if result:
        return result

    # Step 2: strip trailing noise suffixes (longest first to avoid partial strips)
    lower = raw.lower()
    for suffix in sorted(_NOISE_SUFFIXES, key=len, reverse=True):
        if lower.endswith(" " + suffix):
            stripped = raw[:-(len(suffix) + 1)].strip()
            if stripped:
                result = _query(stripped)
                if result:
                    return result
            break  # only strip one suffix per candidate

    return None


def _find_existing_relationship(db, subject: str, object_name: str) -> Optional[str]:
    """Return the ID of any existing relationship for (subject, object), any relation_type.

    Returns the UUID string of the highest-confidence existing row, or None.
    Prefers rows where operator_reviewed=TRUE (seeded rows) over machine candidates.
    """
    from sqlalchemy import text
    row = db.execute(text(
        "SELECT id FROM fragrance_relationships "
        "WHERE subject_canonical_name = :subject "
        "  AND object_canonical_name = :object "
        "ORDER BY operator_reviewed DESC, confidence_score DESC "
        "LIMIT 1"
    ), {"subject": subject, "object": object_name}).fetchone()
    return str(row[0]) if row else None


def _evidence_already_exists(db, relationship_id: str, query_text: str) -> bool:
    """Return True if a cross_query_retrieval evidence row already exists for this pair."""
    from sqlalchemy import text
    row = db.execute(text(
        "SELECT 1 FROM relationship_evidence "
        "WHERE relationship_id = :rid "
        f"  AND evidence_type = '{EVIDENCE_TYPE}' "
        "  AND query_text = :qt "
        "LIMIT 1"
    ), {"rid": relationship_id, "qt": query_text}).fetchone()
    return row is not None


def _insert_relationship(db, subject: str, object_name: str, confidence: float,
                         today: date) -> str:
    """Insert a new machine-generated relationship candidate.

    Uses ON CONFLICT DO NOTHING — if the pair already exists under
    commonly_compared_to (e.g. from a prior run), the existing row is used.

    Returns the relationship UUID string (either newly created or existing).
    """
    from sqlalchemy import text
    rel_id = str(uuid.uuid4())
    db.execute(text(
        "INSERT INTO fragrance_relationships "
        "(id, subject_canonical_name, relation_type, object_canonical_name, "
        " confidence_score, is_public, operator_reviewed, "
        " first_observed_date, last_confirmed_date, formula_version) "
        "VALUES (:id, :subject, :rtype, :object, :conf, FALSE, FALSE, "
        " :first_date, :last_date, :fv) "
        "ON CONFLICT (subject_canonical_name, relation_type, object_canonical_name) "
        "DO NOTHING"
    ), {
        "id": rel_id,
        "subject": subject,
        "rtype": RELATION_TYPE_DEFAULT,
        "object": object_name,
        "conf": confidence,
        "first_date": today,
        "last_date": today,
        "fv": FORMULA_VERSION,
    })
    # Fetch the actual row ID (may differ from rel_id if ON CONFLICT fired)
    row = db.execute(text(
        "SELECT id FROM fragrance_relationships "
        "WHERE subject_canonical_name = :subject "
        "  AND relation_type = :rtype "
        "  AND object_canonical_name = :object "
        "LIMIT 1"
    ), {"subject": subject, "rtype": RELATION_TYPE_DEFAULT, "object": object_name}).fetchone()
    return str(row[0]) if row else rel_id


def _insert_evidence(db, relationship_id: str, query_text: str, today: date):
    """Insert a cross_query_retrieval evidence row.

    Caller must check _evidence_already_exists() before calling to maintain
    idempotency (no DB-level unique constraint on evidence).
    """
    from sqlalchemy import text
    ev_id = str(uuid.uuid4())
    db.execute(text(
        "INSERT INTO relationship_evidence "
        "(id, relationship_id, evidence_type, query_text, observed_date) "
        f"VALUES (:id, :rid, '{EVIDENCE_TYPE}', :qt, :obs)"
    ), {
        "id": ev_id,
        "rid": relationship_id,
        "qt": query_text,
        "obs": today,
    })


# ---------------------------------------------------------------------------
# Core harvesting logic
# ---------------------------------------------------------------------------

def harvest(
    db,
    dry_run: bool = True,
    min_occurrences: int = DEFAULT_MIN_OCCURRENCES,
    entity_limit: int = DEFAULT_ENTITY_LIMIT,
) -> dict:
    """Run the evidence harvesting pass.

    Returns a summary dict with counts and example candidates.
    """
    today = date.today()

    print(f"[FTG-4] harvest starting — dry_run={dry_run}, "
          f"min_occurrences={min_occurrences}, entity_limit={entity_limit}")

    # Step 1: fetch all query topic rows with occurrence counts
    print("[FTG-4] fetching query topics from entity_topic_links …")
    topic_rows = _fetch_entity_queries(db, min_occurrences=min_occurrences,
                                       limit=entity_limit)
    print(f"[FTG-4] fetched {len(topic_rows)} query rows across all entities")

    # Step 2: group query strings by entity (canonical_name)
    entity_queries: dict[str, dict] = {}  # canonical_name → {queries: list, entity_id: str}
    query_occ_map: dict[str, dict[str, int]] = defaultdict(dict)  # canonical_name → {query: occ}
    entity_count = 0

    for row in topic_rows:
        cname = row["canonical_name"]
        if cname not in entity_queries:
            entity_queries[cname] = {
                "entity_id": row["entity_id"],
                "queries": [],
            }
            entity_count += 1
            if entity_count > entity_limit:
                break
        entity_queries[cname]["queries"].append(row["query_text"])
        query_occ_map[cname][row["query_text"]] = row["occurrence_count"]

    print(f"[FTG-4] processing {len(entity_queries)} distinct entities")

    # Step 3: extract VS/co-retrieval candidates and resolve
    stats = {
        "entities_processed": 0,
        "candidates_resolved": 0,
        "evidence_added_to_existing": 0,
        "evidence_skipped_duplicate": 0,
        # Hard gate: cross_query_retrieval never creates new relationship rows.
        # Only pairs that already exist in fragrance_relationships receive evidence.
        "candidates_skipped_no_existing_relationship": 0,
        "examples": [],
    }

    for canonical_name, entity_info in entity_queries.items():
        queries = entity_info["queries"][:MAX_CANDIDATES_PER_ENTITY]
        raw_candidates = extract_vs_competitors(queries, canonical_name)
        stats["entities_processed"] += 1

        for candidate_str in raw_candidates[:MAX_CANDIDATES_PER_ENTITY]:
            resolved = _resolve_candidate(db, candidate_str)
            if not resolved or resolved == canonical_name:
                continue
            stats["candidates_resolved"] += 1

            # Determine total occurrence count for this (subject, resolved) pair.
            # Match queries containing the resolved canonical name or the raw
            # candidate string (both indicate the same co-retrieval signal).
            resolved_lower = resolved.lower()
            cand_lower = candidate_str.lower()
            total_occ = 0
            matching_queries = []
            for q, occ in query_occ_map[canonical_name].items():
                q_lower = q.lower()
                if resolved_lower in q_lower or cand_lower in q_lower:
                    total_occ += occ
                    matching_queries.append(q)

            if total_occ < min_occurrences:
                continue

            # Step 4: check for existing relationship (any relation_type).
            # HARD GATE: cross_query_retrieval evidence may only be attached to
            # existing operator-reviewed relationship rows.  Do not create new
            # machine candidate rows from co-retrieval evidence alone — the signal
            # is too weak to justify a new relationship claim without corroboration.
            existing_id = _find_existing_relationship(db, canonical_name, resolved)

            if existing_id is None:
                stats["candidates_skipped_no_existing_relationship"] += 1
                continue

            example = {
                "subject": canonical_name,
                "object": resolved,
                "existing_relation": "EXISTING",
                "evidence_type": EVIDENCE_TYPE,
                "evidence_count": len(matching_queries),
                "action": "ATTACH" if not dry_run else "WOULD_ATTACH",
            }

            if dry_run:
                stats["examples"].append(example)
                stats["evidence_added_to_existing"] += len(matching_queries)
                continue

            # Write mode — attach evidence only
            for q in matching_queries:
                if _evidence_already_exists(db, existing_id, q):
                    stats["evidence_skipped_duplicate"] += 1
                else:
                    _insert_evidence(db, existing_id, q, today)
                    stats["evidence_added_to_existing"] += 1

            stats["examples"].append(example)

    if not dry_run:
        db.commit()
        print("[FTG-4] committed")
    else:
        print("[FTG-4] dry-run complete — no writes performed")

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="FTG-4 / RI1-E — Relationship evidence harvesting"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Preview only — do not write to DB",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_ENTITY_LIMIT,
        help=f"Max entities to process (default {DEFAULT_ENTITY_LIMIT})",
    )
    parser.add_argument(
        "--min-occurrences",
        type=int,
        default=DEFAULT_MIN_OCCURRENCES,
        help=f"Min query occurrence count to generate a candidate (default {DEFAULT_MIN_OCCURRENCES})",
    )
    args = parser.parse_args()

    factory = get_session_factory()
    db = factory()
    try:
        stats = harvest(
            db,
            dry_run=args.dry_run,
            min_occurrences=args.min_occurrences,
            entity_limit=args.limit,
        )
    finally:
        db.close()

    mode = "DRY-RUN" if args.dry_run else "WRITE"
    print(f"\n[FTG-4] {mode} RESULTS")
    print(f"  entities_processed:          {stats['entities_processed']}")
    print(f"  candidates_resolved:         {stats['candidates_resolved']}")
    print(f"  evidence_added_to_existing:            {stats['evidence_added_to_existing']}")
    print(f"  evidence_skipped_duplicate:            {stats['evidence_skipped_duplicate']}")
    print(f"  candidates_skipped_no_existing_rel:    {stats['candidates_skipped_no_existing_relationship']}")

    if stats["examples"]:
        print(f"\n[FTG-4] EVIDENCE ATTACHMENT ROWS (first {min(10, len(stats['examples']))}):")
        print(f"  {'Subject':<40} {'Object':<35} {'Ev Type':<22} {'Rows':>4} {'Action'}")
        print(f"  {'-'*40} {'-'*35} {'-'*22} {'-':>4} {'-'*12}")
        for ex in stats["examples"][:10]:
            print(f"  {ex['subject'][:40]:<40} {ex['object'][:35]:<35} "
                  f"{ex['evidence_type'][:22]:<22} {ex['evidence_count']:>4} {ex['action']}")
        print(f"  (Rows = distinct query strings that would become relationship_evidence rows)")

    if args.dry_run and stats["evidence_added_to_existing"] > 0:
        print(f"\n[FTG-4] Re-run without --dry-run to attach "
              f"{stats['evidence_added_to_existing']} cross_query_retrieval evidence rows "
              f"to existing canonical relationships.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
