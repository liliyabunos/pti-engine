"""FTG-4 / RI1-E — Relationship Evidence Harvesting v1.

Harvests relationship candidates from internal query signals in entity_topic_links.
Creates operator-reviewable fragrance_relationship candidates (is_public=FALSE,
operator_reviewed=FALSE) and appends query_pattern evidence to existing relationships.

Internal signal source (chosen over alternatives):
  entity_topic_links WHERE topic_type='query' — YouTube search queries already
  stored structurally per entity per cycle.  These are the highest-signal source
  because they are actual user search strings that drove content discovery, not
  raw text that needs parsing.  The extract_vs_competitors() function is already
  tuned for this source.

  Alternative rejected: raw text NLP on canonical_content_items — requires broad
  text parsing, much higher false-positive rate, no existing extraction path.

Idempotency rules:
  - fragrance_relationships has UNIQUE on
      (subject_canonical_name, relation_type, object_canonical_name)
    → INSERT ON CONFLICT DO NOTHING prevents duplicate relationship rows.
  - relationship_evidence has no DB-level unique constraint on query_text, so
    the harvester checks for an existing row with the same
      (relationship_id, evidence_type='query_pattern', query_text)
    before inserting evidence — preventing duplicate evidence on repeated runs.

Candidate row rules (FTG-4 public safety contract):
  - operator_reviewed = FALSE  (always — machine candidates are never auto-reviewed)
  - is_public = FALSE          (always — must pass FTG-3 quality gate via human review)
  - relation_type = 'commonly_compared_to'  (conservative — never overclaim dupe_of)

Existing relationship handling:
  If a (subject, object) pair already exists in fragrance_relationships under ANY
  relation_type, the harvester attaches query evidence to the existing row instead
  of creating a new candidate.  This strengthens the evidence trail behind seeded
  canonical rows without creating duplicates.

Confidence policy (machine-generated, must never reach 0.700 gate automatically):
  occurrence_count 1–2  → 0.200
  occurrence_count 3–5  → 0.250
  occurrence_count 6–10 → 0.300
  occurrence_count 11+  → 0.350

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

EVIDENCE_TYPE = "query_pattern"
RELATION_TYPE_DEFAULT = "commonly_compared_to"
FORMULA_VERSION = 1

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
    """Return machine confidence score for a query_pattern evidence observation.

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

    Attempts case-insensitive exact match on entity_market.canonical_name.
    Returns the canonical_name from entity_market if matched, else None.
    Does NOT use the resolver alias table (v1 is conservative — exact match only).
    """
    from sqlalchemy import text
    row = db.execute(text(
        "SELECT canonical_name FROM entity_market "
        "WHERE entity_type = 'perfume' "
        "  AND LOWER(canonical_name) = LOWER(:cand) "
        "LIMIT 1"
    ), {"cand": candidate_str.strip()}).fetchone()
    return row[0] if row else None


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
    """Return True if a query_pattern evidence row already exists for this pair."""
    from sqlalchemy import text
    row = db.execute(text(
        "SELECT 1 FROM relationship_evidence "
        "WHERE relationship_id = :rid "
        "  AND evidence_type = 'query_pattern' "
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
    """Insert a query_pattern evidence row.

    Caller must check _evidence_already_exists() before calling to maintain
    idempotency (no DB-level unique constraint on evidence).
    """
    from sqlalchemy import text
    ev_id = str(uuid.uuid4())
    db.execute(text(
        "INSERT INTO relationship_evidence "
        "(id, relationship_id, evidence_type, query_text, observed_date) "
        "VALUES (:id, :rid, 'query_pattern', :qt, :obs)"
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

    # Step 3: extract VS candidates and resolve
    stats = {
        "entities_processed": 0,
        "candidates_resolved": 0,
        "new_relationships": 0,
        "evidence_added_to_existing": 0,
        "evidence_skipped_duplicate": 0,
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
            # Count queries that contain either the raw candidate string or the
            # resolved canonical name — both indicate the same comparison signal.
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

            confidence = _compute_confidence(total_occ)

            # Step 4: check for existing relationship (any relation_type)
            existing_id = _find_existing_relationship(db, canonical_name, resolved)
            is_new_row = existing_id is None

            example = {
                "subject": canonical_name,
                "object": resolved,
                "relation": RELATION_TYPE_DEFAULT if is_new_row else "EXISTING",
                "evidence_count": len(matching_queries),
                "confidence": confidence if is_new_row else "n/a (existing)",
                "new_row": is_new_row,
            }

            if dry_run:
                stats["examples"].append(example)
                if is_new_row:
                    stats["new_relationships"] += 1
                else:
                    stats["evidence_added_to_existing"] += 1
                continue

            # Write mode
            if is_new_row:
                rel_id = _insert_relationship(db, canonical_name, resolved, confidence, today)
                stats["new_relationships"] += 1
            else:
                rel_id = existing_id

            # Add evidence for each distinct matching query string
            for q in matching_queries:
                if _evidence_already_exists(db, rel_id, q):
                    stats["evidence_skipped_duplicate"] += 1
                else:
                    _insert_evidence(db, rel_id, q, today)
                    if is_new_row:
                        pass  # counted above
                    else:
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
    print(f"  new_relationships:           {stats['new_relationships']}")
    print(f"  evidence_added_to_existing:  {stats['evidence_added_to_existing']}")
    print(f"  evidence_skipped_duplicate:  {stats['evidence_skipped_duplicate']}")

    if stats["examples"]:
        print(f"\n[FTG-4] EXAMPLE CANDIDATES (first {min(10, len(stats['examples']))}):")
        print(f"  {'Subject':<40} {'Object':<40} {'Relation':<25} {'Ev':>3} {'Conf':>6} {'New'}")
        print(f"  {'-'*40} {'-'*40} {'-'*25} {'-':>3} {'-':>6} {'-'*3}")
        for ex in stats["examples"][:10]:
            conf_str = f"{ex['confidence']:.3f}" if isinstance(ex["confidence"], float) else str(ex["confidence"])
            print(f"  {ex['subject'][:40]:<40} {ex['object'][:40]:<40} "
                  f"{ex['relation'][:25]:<25} {ex['evidence_count']:>3} {conf_str:>6} "
                  f"{'YES' if ex['new_row'] else 'NO'}")

    if args.dry_run and (stats["new_relationships"] > 0 or stats["evidence_added_to_existing"] > 0):
        print(f"\n[FTG-4] Re-run without --dry-run to write {stats['new_relationships']} "
              f"new relationship candidates and {stats['evidence_added_to_existing']} evidence additions.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
