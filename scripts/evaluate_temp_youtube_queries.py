#!/usr/bin/env python3
"""Phase G4-E.4 — Evaluate Temporary YouTube Query Experiments.

For each active experiment in youtube_query_experiments, this script:
  1. Finds content items fetched during the experiment window (time-window +
     title-matching against candidate_text / query_text keywords).
  2. Counts: videos_fetched, entity_mentions_count, fragrance_candidates_produced,
     resolved_mentions_count.
  3. Builds evidence_json (top entities, sample titles, channel sources).
  4. Updates the experiment row with accumulated counts, run_count, last_run_at.
  5. Sets a recommendation: confirm | suppress | review.

Lifecycle transitions (pending → active handled by apply_temp_youtube_queries.py):
  active → confirmed   (confirm recommendation accepted)
  active → suppressed  (suppress recommendation accepted)

Evaluation thresholds:
  confirm:  entity_mentions_count >= 2  AND  run_count >= 2
  suppress: run_count >= 3  AND  entity_mentions_count == 0
              AND  fragrance_candidates_produced < 3
  review:   anything else

Usage:
    # Dry-run (default): show what would be updated
    python3 scripts/evaluate_temp_youtube_queries.py

    # Apply: write updates to DB
    python3 scripts/evaluate_temp_youtube_queries.py --apply

    # Apply and auto-transition confirmed/suppressed experiments
    python3 scripts/evaluate_temp_youtube_queries.py --apply --auto-transition

    # Evaluate a specific experiment by id
    python3 scripts/evaluate_temp_youtube_queries.py --id 3

    # Bump run_count even when no new content found (for quota-tracking)
    python3 scripts/evaluate_temp_youtube_queries.py --apply --bump-run-count
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import psycopg2
    import psycopg2.extras
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

CONFIRM_MIN_MENTIONS = 2      # entity_mentions_count threshold for confirm
CONFIRM_MIN_RUNS = 2          # run_count must be >= this to confirm
SUPPRESS_MIN_RUNS = 3         # run_count must be >= this to suppress
SUPPRESS_MAX_MENTIONS = 0     # entity_mentions_count must be <= this to suppress
SUPPRESS_MAX_CANDIDATES = 2   # fragrance_candidates_produced must be <= this to suppress

# Max keywords extracted from query_text/candidate_text for title ILIKE matching
MAX_KEYWORDS = 4

# Minimum keyword length to use in ILIKE (avoids short noise tokens)
MIN_KEYWORD_LEN = 3

# Max content items to pull per experiment for evidence building
EVIDENCE_LIMIT = 50

# Max sample titles / entities / channels in evidence_json
EVIDENCE_MAX_TITLES = 5
EVIDENCE_MAX_ENTITIES = 10
EVIDENCE_MAX_CHANNELS = 5

# ---------------------------------------------------------------------------
# Keyword extraction helpers
# ---------------------------------------------------------------------------

_STOP_WORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "to",
    "for", "by", "with", "from", "is", "was", "be", "it",
    "perfume", "fragrance", "cologne", "parfum", "review", "scent",
    "best", "top", "new", "my",
})


def _extract_keywords(candidate_text: str, query_text: str) -> List[str]:
    """Extract meaningful search keywords from candidate and query texts.

    Returns a list of lower-cased keywords suitable for ILIKE matching,
    ordered by length (longest first — more specific matches first).
    """
    # Combine both texts, deduplicate tokens
    combined = f"{candidate_text} {query_text}".lower()
    # Remove punctuation
    combined = re.sub(r"[^\w\s]", " ", combined)
    tokens = [t for t in combined.split() if len(t) >= MIN_KEYWORD_LEN and t not in _STOP_WORDS]

    # Deduplicate preserving order
    seen: set[str] = set()
    unique: List[str] = []
    for tok in tokens:
        if tok not in seen:
            seen.add(tok)
            unique.append(tok)

    # Sort longest first (more specific), cap at MAX_KEYWORDS
    unique.sort(key=len, reverse=True)
    return unique[:MAX_KEYWORDS]


# ---------------------------------------------------------------------------
# DB helpers — content item counting
# ---------------------------------------------------------------------------

def _find_content_items(
    conn,
    experiment: Dict,
    keywords: List[str],
) -> List[Dict]:
    """Return content items that are likely attributable to this experiment.

    Strategy:
      1. Time-window: collected_at >= activated_at (when the experiment went live)
      2. Platform + ingestion method: youtube, search ingestion only
      3. Title matching: ANY of the extracted keywords appears in the title (ILIKE)

    This is a heuristic — the normalizer stores query at top level but it may
    not be persisted to the DB. Title matching is the reliable fallback.
    """
    if not keywords:
        return []

    activated_at = experiment.get("activated_at")
    if activated_at is None:
        return []

    # Build ILIKE clauses: title ILIKE '%keyword%' OR ...
    ilike_clauses = " OR ".join([
        f"LOWER(title) LIKE '%' || %s || '%'"
        for _ in keywords
    ])
    kw_lower = [kw.lower() for kw in keywords]

    sql = f"""
        SELECT
            id,
            title,
            source_account_handle,
            source_account_id,
            media_metadata,
            collected_at,
            published_at
        FROM canonical_content_items
        WHERE source_platform = 'youtube'
          AND ingestion_method = 'search'
          AND collected_at >= %s
          AND ({ilike_clauses})
        ORDER BY collected_at DESC
        LIMIT %s
    """
    params = [activated_at] + kw_lower + [EVIDENCE_LIMIT]

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _count_entity_mentions(conn, content_item_ids: List[str]) -> int:
    """Count entity_mentions rows linked to these content item IDs."""
    if not content_item_ids:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM entity_mentions WHERE source_url = ANY(%s)",
            (content_item_ids,)
        )
        return cur.fetchone()[0]


def _count_fragrance_candidates(
    conn,
    experiment: Dict,
    activated_at: datetime,
) -> int:
    """Count fragrance_candidates rows with matching normalized_text that appeared
    after the experiment was activated.

    This measures whether the temp query is surfacing unresolved entities
    (potential new discoveries) even if they don't resolve to known entities yet.
    """
    normalized = experiment.get("normalized_candidate", "")
    if not normalized:
        return 0

    # Use a broad match: the candidate's normalized text as a prefix/substring
    # because fragrance_candidates stores raw extracted text
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM fragrance_candidates
            WHERE (
                normalized_text = %s
                OR normalized_text LIKE %s
            )
            AND last_seen >= %s
            """,
            (normalized, f"{normalized}%", activated_at)
        )
        return cur.fetchone()[0]


def _count_resolved_mentions(conn, content_item_ids: List[str]) -> int:
    """Count resolved_signals rows for these content items where entities were resolved."""
    if not content_item_ids:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM resolved_signals
            WHERE content_item_id = ANY(%s)
              AND resolved_entities_json IS NOT NULL
              AND resolved_entities_json <> '[]'
              AND resolved_entities_json <> 'null'
            """,
            (content_item_ids,)
        )
        return cur.fetchone()[0]


def _get_top_entities(conn, content_item_ids: List[str]) -> List[str]:
    """Return the top canonical entity names mentioned across these content items."""
    if not content_item_ids:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT em.entity_id, COUNT(*) AS cnt
            FROM entity_mentions em
            WHERE em.source_url = ANY(%s)
            GROUP BY em.entity_id
            ORDER BY cnt DESC
            LIMIT %s
            """,
            (content_item_ids, EVIDENCE_MAX_ENTITIES)
        )
        rows = cur.fetchall()

    if not rows:
        return []

    # Resolve entity_ids to canonical names from entity_market
    entity_ids = [r[0] for r in rows]
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, canonical_name FROM entity_market WHERE id::text = ANY(%s)",
                ([str(eid) for eid in entity_ids],)
            )
            name_map = {str(r[0]): r[1] for r in cur.fetchall()}
    except Exception:
        name_map = {}

    result = []
    for entity_id, cnt in rows:
        name = name_map.get(str(entity_id), str(entity_id))
        result.append(f"{name} ({cnt})")
    return result


# ---------------------------------------------------------------------------
# Evaluation logic
# ---------------------------------------------------------------------------

def _recommend(
    run_count: int,
    entity_mentions_count: int,
    fragrance_candidates_produced: int,
) -> str:
    """Return recommendation string based on accumulated metrics."""
    if entity_mentions_count >= CONFIRM_MIN_MENTIONS and run_count >= CONFIRM_MIN_RUNS:
        return "confirm"
    if (
        run_count >= SUPPRESS_MIN_RUNS
        and entity_mentions_count <= SUPPRESS_MAX_MENTIONS
        and fragrance_candidates_produced <= SUPPRESS_MAX_CANDIDATES
    ):
        return "suppress"
    return "review"


def _build_evidence(
    items: List[Dict],
    top_entities: List[str],
) -> Dict[str, Any]:
    """Build the evidence_json dict for an experiment."""
    sample_titles = [
        item.get("title", "")
        for item in items[:EVIDENCE_MAX_TITLES]
        if item.get("title")
    ]

    channels: List[str] = []
    seen_channels: set[str] = set()
    for item in items:
        ch = item.get("source_account_handle") or ""
        if ch and ch not in seen_channels:
            seen_channels.add(ch)
            channels.append(ch)
        if len(channels) >= EVIDENCE_MAX_CHANNELS:
            break

    return {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "videos_checked": len(items),
        "sample_titles": sample_titles,
        "top_entities": top_entities,
        "channels_contributing": channels,
    }


# ---------------------------------------------------------------------------
# Per-experiment evaluation
# ---------------------------------------------------------------------------

def evaluate_experiment(
    conn,
    experiment: Dict,
    dry_run: bool = True,
    bump_run_count: bool = False,
) -> Dict:
    """Evaluate one experiment. Returns an update dict with new metrics."""
    exp_id = experiment["id"]
    candidate_text = experiment.get("candidate_text", "")
    query_text = experiment.get("query_text", "")
    activated_at = experiment.get("activated_at")
    normalized_candidate = experiment.get("normalized_candidate", "")

    keywords = _extract_keywords(candidate_text, query_text)

    print(f"\n[eval] Experiment id={exp_id} candidate='{candidate_text}' query='{query_text}'")
    print(f"[eval]   keywords={keywords!r}  activated_at={activated_at}")

    # --- find content items ---
    items = _find_content_items(conn, experiment, keywords) if keywords else []
    item_ids = [item["id"] for item in items]

    print(f"[eval]   content items matched: {len(item_ids)}")

    # --- count metrics ---
    new_videos = len(item_ids)
    new_entity_mentions = _count_entity_mentions(conn, item_ids) if item_ids else 0
    new_candidates = _count_fragrance_candidates(conn, experiment, activated_at) if activated_at else 0
    new_resolved = _count_resolved_mentions(conn, item_ids) if item_ids else 0

    # Accumulate with existing counts
    prev_videos = experiment.get("videos_fetched") or 0
    prev_mentions = experiment.get("entity_mentions_count") or 0
    prev_candidates = experiment.get("fragrance_candidates_produced") or 0
    prev_resolved = experiment.get("resolved_mentions_count") or 0
    prev_runs = experiment.get("run_count") or 0

    total_videos = max(prev_videos, new_videos)  # take max (idempotent within window)
    total_mentions = max(prev_mentions, new_entity_mentions)
    total_candidates = max(prev_candidates, new_candidates)
    total_resolved = max(prev_resolved, new_resolved)
    new_run_count = prev_runs + (1 if (new_videos > 0 or bump_run_count) else 0)

    # Build recommendation
    recommendation = _recommend(new_run_count, total_mentions, total_candidates)

    # Build evidence
    top_entities = _get_top_entities(conn, item_ids) if item_ids else []
    evidence = _build_evidence(items, top_entities)

    print(f"[eval]   videos_fetched={total_videos}  entity_mentions={total_mentions}  "
          f"candidates={total_candidates}  resolved={total_resolved}  "
          f"run_count={new_run_count}  recommendation={recommendation}")

    update = {
        "id": exp_id,
        "videos_fetched": total_videos,
        "entity_mentions_count": total_mentions,
        "fragrance_candidates_produced": total_candidates,
        "resolved_mentions_count": total_resolved,
        "run_count": new_run_count,
        "last_run_at": datetime.now(timezone.utc),
        "first_run_at": experiment.get("first_run_at") or (
            datetime.now(timezone.utc) if new_videos > 0 else None
        ),
        "recommendation": recommendation,
        "evidence_json": json.dumps(evidence),
    }

    return update


# ---------------------------------------------------------------------------
# DB write helpers
# ---------------------------------------------------------------------------

def _apply_update(conn, update: Dict) -> None:
    """Write evaluation results back to youtube_query_experiments."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE youtube_query_experiments SET
                videos_fetched = %(videos_fetched)s,
                entity_mentions_count = %(entity_mentions_count)s,
                fragrance_candidates_produced = %(fragrance_candidates_produced)s,
                resolved_mentions_count = %(resolved_mentions_count)s,
                run_count = %(run_count)s,
                last_run_at = %(last_run_at)s,
                first_run_at = COALESCE(first_run_at, %(first_run_at)s),
                recommendation = %(recommendation)s,
                evidence_json = %(evidence_json)s
            WHERE id = %(id)s
            """,
            update,
        )
    conn.commit()


def _auto_transition(conn, experiment: Dict, recommendation: str, dry_run: bool) -> None:
    """Transition experiment status based on recommendation if --auto-transition is set."""
    exp_id = experiment["id"]
    current_status = experiment.get("status", "")

    if current_status != "active":
        return

    if recommendation == "confirm":
        new_status = "confirmed"
    elif recommendation == "suppress":
        new_status = "suppressed"
    else:
        return  # review — do not auto-transition

    print(f"[eval] {'Would auto-transition' if dry_run else 'Auto-transitioning'} "
          f"id={exp_id} status: {current_status} → {new_status}")

    if not dry_run:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE youtube_query_experiments SET status = %s WHERE id = %s",
                (new_status, exp_id)
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Status display
# ---------------------------------------------------------------------------

def _print_evaluation_summary(updates: List[Dict], experiments: List[Dict]) -> None:
    """Print a summary table of evaluation results."""
    exp_map = {e["id"]: e for e in experiments}

    print(f"\n{'ID':>4}  {'Candidate':<35}  {'Runs':>4}  {'Videos':>6}  "
          f"{'Mentions':>8}  {'Candidates':>10}  {'Rec':<10}")
    print("-" * 90)

    for upd in updates:
        exp = exp_map.get(upd["id"], {})
        name = (exp.get("candidate_text") or "")[:34]
        print(
            f"{upd['id']:>4}  {name:<35}  {upd['run_count']:>4}  "
            f"{upd['videos_fetched']:>6}  {upd['entity_mentions_count']:>8}  "
            f"{upd['fragrance_candidates_produced']:>10}  {upd['recommendation']:<10}"
        )
    print()

    by_rec: Dict[str, int] = {}
    for upd in updates:
        rec = upd["recommendation"]
        by_rec[rec] = by_rec.get(rec, 0) + 1
    for rec, cnt in sorted(by_rec.items()):
        print(f"  {rec}: {cnt}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase G4-E.4 — Evaluate temporary YouTube query experiments"
    )
    parser.add_argument("--apply", action="store_true", default=False,
                        help="Write evaluation results to DB (default: dry-run)")
    parser.add_argument("--auto-transition", action="store_true", default=False,
                        help="Automatically transition confirmed/suppressed experiments "
                             "(requires --apply)")
    parser.add_argument("--bump-run-count", action="store_true", default=False,
                        help="Increment run_count even when no new content found "
                             "(for quota tracking when pipeline ran but yielded nothing)")
    parser.add_argument("--id", type=int, default=None,
                        help="Evaluate only the experiment with this ID")
    parser.add_argument("--status", action="store_true", default=False,
                        help="Show current experiment status and exit (no evaluation)")
    args = parser.parse_args()

    dry_run = not args.apply

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("[eval] ERROR: DATABASE_URL is required.", file=sys.stderr)
        sys.exit(1)
    if not HAS_PSYCOPG2:
        print("[eval] ERROR: psycopg2 is required.", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(database_url)
    try:
        if args.status:
            _print_status_table(conn)
            return

        # Load experiments
        experiment_filter = ""
        filter_params: List[Any] = []
        if args.id is not None:
            experiment_filter = "AND id = %s"
            filter_params.append(args.id)

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT id, candidate_text, normalized_candidate, candidate_type,
                       candidate_source, candidate_id, candidate_score,
                       distinct_channels_count, risk_level,
                       query_text, status, created_at, expires_at, activated_at,
                       first_run_at, last_run_at, run_count, videos_fetched,
                       entity_mentions_count, fragrance_candidates_produced,
                       resolved_mentions_count, evidence_json, recommendation, notes
                FROM youtube_query_experiments
                WHERE status = 'active'
                  AND (expires_at IS NULL OR expires_at > NOW())
                  {experiment_filter}
                ORDER BY candidate_score DESC
                """,
                filter_params,
            )
            experiments = [dict(r) for r in cur.fetchall()]

        if not experiments:
            print("[eval] No active experiments to evaluate.")
            return

        print(f"[eval] Evaluating {len(experiments)} active experiment(s) "
              f"({'dry-run' if dry_run else 'APPLY'})")

        updates: List[Dict] = []
        for exp in experiments:
            update = evaluate_experiment(
                conn, exp, dry_run=dry_run, bump_run_count=args.bump_run_count
            )
            updates.append(update)

            if not dry_run:
                _apply_update(conn, update)
                print(f"[eval]   ✓ Updated experiment id={exp['id']}")

                if args.auto_transition:
                    _auto_transition(conn, exp, update["recommendation"], dry_run=False)

        _print_evaluation_summary(updates, experiments)

        if dry_run:
            print(f"\n[eval] DRY-RUN complete. Run with --apply to write changes.")
        else:
            print(f"\n[eval] Evaluation complete. {len(updates)} experiment(s) updated.")

    finally:
        conn.close()


def _print_status_table(conn) -> None:
    """Print full status table of all experiments."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, candidate_text, query_text, status, risk_level,
                   candidate_score, run_count, videos_fetched,
                   entity_mentions_count, fragrance_candidates_produced,
                   recommendation, created_at, expires_at, activated_at,
                   last_run_at
            FROM youtube_query_experiments
            ORDER BY status, candidate_score DESC
            """
        )
        rows = [dict(r) for r in cur.fetchall()]

    if not rows:
        print("[eval] No experiments in youtube_query_experiments table.")
        return

    print(f"\n{'ID':>4}  {'Status':<12}  {'Risk':<6}  {'Score':>6}  "
          f"{'Runs':>4}  {'Vids':>5}  {'Ment':>5}  {'Cand':>5}  "
          f"{'Rec':<10}  {'Candidate'}")
    print("-" * 100)

    for r in rows:
        expires = r["expires_at"].strftime("%m-%d") if r.get("expires_at") else "—"
        name = (r["candidate_text"] or "")[:34]
        rec = r.get("recommendation") or "—"
        print(
            f"{r['id']:>4}  {r['status']:<12}  {r['risk_level']:<6}  "
            f"{r['candidate_score']:>6.3f}  {r['run_count']:>4}  "
            f"{r['videos_fetched']:>5}  {r['entity_mentions_count']:>5}  "
            f"{r['fragrance_candidates_produced']:>5}  "
            f"{rec:<10}  {name} (exp {expires})"
        )
    print()

    active_count = sum(1 for r in rows if r["status"] == "active")
    confirmed_count = sum(1 for r in rows if r["status"] == "confirmed")
    suppressed_count = sum(1 for r in rows if r["status"] == "suppressed")
    print(f"Active: {active_count}  Confirmed: {confirmed_count}  Suppressed: {suppressed_count}")


if __name__ == "__main__":
    main()
