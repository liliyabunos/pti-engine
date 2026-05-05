#!/usr/bin/env python3
"""Phase G4-E.3 — Apply Temporary YouTube Query Experiments.

Reads top emerging candidates from select_emerging_query_candidates output,
inserts approved experiments into youtube_query_experiments table, and
generates a runtime-only YAML file for use by ingest_youtube.py.

The core perfume_queries.yaml is NEVER modified.

Safety constraints:
  - Hard cap: max 5 active experiments at one time (quota budget)
  - Default expiry: 14 days
  - Default dry-run: --apply flag required for any writes
  - query_text UNIQUE constraint prevents accidental duplicates
  - Auto-expires stale active experiments before checking cap

Quota budget:
  5 temp queries × 100 units × 1 run/day (morning only) = 500 units
  47 core queries × 100 units × 2 runs/day = 9,400 units
  Total: 9,900 / 10,000 units (within daily limit)

Usage:
    # Dry-run (default): show what would be inserted and temp YAML contents
    python3 scripts/apply_temp_youtube_queries.py

    # Apply: insert into DB + write temp YAML
    python3 scripts/apply_temp_youtube_queries.py --apply

    # Apply with custom batch size
    python3 scripts/apply_temp_youtube_queries.py --apply --limit 3

    # Show current active experiments
    python3 scripts/apply_temp_youtube_queries.py --status

    # Generate temp YAML from current active experiments (no new insertions)
    python3 scripts/apply_temp_youtube_queries.py --generate-yaml-only

    # Expire old experiments manually
    python3 scripts/apply_temp_youtube_queries.py --expire-stale --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
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
# Constants
# ---------------------------------------------------------------------------

MAX_ACTIVE_EXPERIMENTS = 5
DEFAULT_EXPIRY_DAYS = 14
TEMP_YAML_PATH = "configs/watchlists/perfume_queries_temp.yaml"
SOURCE_TAG = "g4e_emerging_feedback"

# Candidates that should not be added regardless of score.
# Combines generic single-word terms, content/intent phrases (E3-C/E3-F noise list),
# and structural fragments that are not resolvable perfume or brand names.
_BLOCKLIST: frozenset[str] = frozenset({
    # Generic single-word / short terms
    "fragrance", "cologne", "perfume", "scent", "parfum",
    "review", "best fragrance", "top fragrance",
    # E3-C / E3-F noise phrases (intent/topic fragments, not entity names)
    "go to", "beast mode", "smells like", "smell like", "middle eastern",
    "everyday fragrances", "long lasting", "alternatives to", "better than",
    "complimented fragrances", "every man", "wear the most", "wear the",
    "compliment getter", "signature scent", "need in", "under 100", "under 30",
    "every man should", "fresh summer fragrances", "hyped fragrances",
    "niche fragrance", "mother day fragrance", "buy fragrances", "buy fragrance",
    "stop wearing", "stop wearing this", "game of", "smell expensive",
    "paris corner",  # too generic / geo-modifier
    # Content/channel recommendation phrases
    "game changer", "must wear", "must have", "worth it",
    "date night", "office wear", "compliment magnet",
    # Subphrase fragments (subphrase suppressor handles API; block here too)
    "jean paul", "paul gaultier", "jean paul gaultier",
    "forever wanted",  # subphrase of "azzaro forever wanted"
    "azzaro forever",  # subphrase of "azzaro forever wanted"
})


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _count_active_experiments(conn) -> int:
    """Count experiments that are active and not yet expired."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM youtube_query_experiments
            WHERE status = 'active'
              AND (expires_at IS NULL OR expires_at > NOW())
            """
        )
        return cur.fetchone()[0]


def _expire_stale(conn, dry_run: bool = True) -> int:
    """Mark active experiments with expires_at <= NOW() as expired. Returns count."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, query_text, expires_at
            FROM youtube_query_experiments
            WHERE status = 'active'
              AND expires_at IS NOT NULL
              AND expires_at <= NOW()
            """
        )
        stale = cur.fetchall()

    if not stale:
        return 0

    print(f"[apply] Stale experiments to expire: {len(stale)}")
    for row in stale:
        print(f"[apply]   id={row[0]} query='{row[1]}' expired={row[2]}")

    if not dry_run:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE youtube_query_experiments SET status = 'expired' "
                "WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at <= NOW()"
            )
        conn.commit()
        print(f"[apply] Expired {len(stale)} stale experiments.")

    return len(stale)


def _get_active_experiments(conn) -> List[Dict]:
    """Return all currently active (non-expired) experiments."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, query_text, candidate_text, normalized_candidate,
                   candidate_score, status, created_at, expires_at,
                   run_count, videos_fetched, entity_mentions_count,
                   recommendation
            FROM youtube_query_experiments
            WHERE status = 'active'
              AND (expires_at IS NULL OR expires_at > NOW())
            ORDER BY candidate_score DESC
            """
        )
        return [dict(r) for r in cur.fetchall()]


def _get_existing_normalized_candidates(conn) -> set[str]:
    """Return all normalized_candidate values that are not suppressed/expired."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT normalized_candidate FROM youtube_query_experiments "
            "WHERE status NOT IN ('suppressed', 'expired')"
        )
        return {row[0] for row in cur.fetchall()}


def _insert_experiment(conn, row: Dict, expiry_days: int) -> bool:
    """Insert one experiment. Returns True if inserted, False if skipped (conflict)."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=expiry_days)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO youtube_query_experiments (
                    candidate_text, normalized_candidate, candidate_type,
                    candidate_source, candidate_id, candidate_score,
                    distinct_channels_count, risk_level,
                    query_text, status, source, created_at, expires_at, activated_at
                ) VALUES (
                    %(candidate_text)s, %(normalized_candidate)s, %(candidate_type)s,
                    %(candidate_source)s, %(candidate_id)s, %(candidate_score)s,
                    %(distinct_channels)s, %(risk_level)s,
                    %(query_text)s, 'active', %(source)s, NOW(), %(expires_at)s, NOW()
                )
                ON CONFLICT (normalized_candidate) DO NOTHING
                """,
                {
                    "candidate_text": row["display_name"],
                    "normalized_candidate": row["normalized_text"],
                    "candidate_type": row.get("candidate_type", "perfume"),
                    "candidate_source": row.get("source", "emerging_signals"),
                    "candidate_id": row.get("candidate_id"),
                    "candidate_score": row.get("candidate_score", 0.0),
                    "distinct_channels": row.get("distinct_channels", 0),
                    "risk_level": row.get("risk_level", "medium"),
                    "query_text": row["recommended_query"],
                    "source": SOURCE_TAG,
                    "expires_at": expires_at,
                },
            )
        conn.commit()
        return cur.rowcount > 0
    except Exception as exc:
        conn.rollback()
        print(f"[apply] ERROR inserting '{row['display_name']}': {exc}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# YAML generation
# ---------------------------------------------------------------------------

def _generate_temp_yaml(active_experiments: List[Dict]) -> str:
    """Generate temp YAML content from active experiments."""
    lines = [
        "# AUTO-GENERATED — DO NOT EDIT MANUALLY",
        "# Phase G4-E temporary YouTube query experiments.",
        "# Generated by: scripts/apply_temp_youtube_queries.py",
        f"# Generated at: {datetime.now(timezone.utc).isoformat()}",
        f"# Active experiments: {len(active_experiments)}",
        "#",
        "# These queries run ONCE per day (morning pipeline only, Step 1.5).",
        "# They expire after 14 days and are removed from this file automatically.",
        "# Core perfume_queries.yaml is NEVER modified by this system.",
        "#",
        "queries:",
    ]
    for exp in active_experiments:
        expires = exp.get("expires_at")
        expires_str = expires.strftime("%Y-%m-%d") if expires else "no-expiry"
        lines.append(f"  # Experiment id={exp['id']} | candidate='{exp['candidate_text']}' | expires={expires_str}")
        lines.append(f"  - {exp['query_text']!r}")
    return "\n".join(lines) + "\n"


def _write_temp_yaml(active_experiments: List[Dict], path: str = TEMP_YAML_PATH, dry_run: bool = True) -> None:
    """Write or display the temp YAML."""
    content = _generate_temp_yaml(active_experiments)
    if dry_run:
        print(f"\n[apply] Would write {len(active_experiments)} queries to {path}:")
        print("-" * 60)
        print(content)
        print("-" * 60)
    else:
        Path(path).write_text(content, encoding="utf-8")
        print(f"[apply] Wrote {len(active_experiments)} queries to {path}")


# ---------------------------------------------------------------------------
# Status display
# ---------------------------------------------------------------------------

def _print_status(conn) -> None:
    """Print current experiment status table."""
    with psycopg2.extras.RealDictCursor(conn) as cur:
        cur.execute(
            """
            SELECT id, candidate_text, query_text, status, risk_level,
                   candidate_score, run_count, videos_fetched,
                   entity_mentions_count, recommendation,
                   created_at, expires_at
            FROM youtube_query_experiments
            ORDER BY status, candidate_score DESC
            """
        )
        rows = [dict(r) for r in cur.fetchall()]

    if not rows:
        print("[apply] No experiments in youtube_query_experiments table.")
        return

    print(f"\n{'ID':>4}  {'Status':<12}  {'Risk':<6}  {'Score':>6}  {'Runs':>4}  {'Vids':>5}  {'Mentions':>8}  {'Candidate':<35}  Expires")
    print("-" * 110)
    for r in rows:
        expires = r["expires_at"].strftime("%Y-%m-%d") if r.get("expires_at") else "—"
        name = (r["candidate_text"] or "")[:34]
        print(
            f"{r['id']:>4}  {r['status']:<12}  {r['risk_level']:<6}  "
            f"{r['candidate_score']:>6.3f}  {r['run_count']:>4}  {r['videos_fetched']:>5}  "
            f"{r['entity_mentions_count']:>8}  {name:<35}  {expires}"
        )
    print()

    active_count = sum(1 for r in rows if r["status"] == "active")
    print(f"Active: {active_count}/{MAX_ACTIVE_EXPERIMENTS} (quota budget)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase G4-E.3 — Apply temp YouTube query experiments"
    )
    parser.add_argument("--apply", action="store_true", default=False,
                        help="Write to DB and generate temp YAML (default: dry-run)")
    parser.add_argument("--limit", type=int, default=5,
                        help="Max new experiments to add per run (default: 5)")
    parser.add_argument("--expiry-days", type=int, default=DEFAULT_EXPIRY_DAYS,
                        help=f"Days until experiments expire (default: {DEFAULT_EXPIRY_DAYS})")
    parser.add_argument("--min-channels", type=int, default=2,
                        help="Min distinct channels filter for candidate selection (default: 2)")
    parser.add_argument("--days", type=int, default=14,
                        help="Lookback window for emerging_signals (default: 14)")
    parser.add_argument("--status", action="store_true", default=False,
                        help="Show current experiment status and exit")
    parser.add_argument("--generate-yaml-only", action="store_true", default=False,
                        help="Regenerate temp YAML from active experiments, no new insertions")
    parser.add_argument("--expire-stale", action="store_true", default=False,
                        help="Expire stale experiments only (use with --apply)")
    parser.add_argument("--yaml-path", type=str, default=TEMP_YAML_PATH,
                        help=f"Output YAML path (default: {TEMP_YAML_PATH})")
    args = parser.parse_args()

    dry_run = not args.apply
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("[apply] ERROR: DATABASE_URL is required.", file=sys.stderr)
        sys.exit(1)
    if not HAS_PSYCOPG2:
        print("[apply] ERROR: psycopg2 is required.", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(database_url)
    try:
        if args.status:
            _print_status(conn)
            return

        # Step 1: Expire stale
        _expire_stale(conn, dry_run=dry_run)

        if args.expire_stale:
            if not dry_run:
                print("[apply] Stale experiments expired.")
            return

        # Step 2: Show / regenerate YAML from existing active experiments
        if args.generate_yaml_only:
            active = _get_active_experiments(conn)
            _write_temp_yaml(active, path=args.yaml_path, dry_run=dry_run)
            return

        # Step 3: How many slots available?
        active_count = _count_active_experiments(conn)
        slots_available = MAX_ACTIVE_EXPERIMENTS - active_count
        print(f"[apply] Active experiments: {active_count}/{MAX_ACTIVE_EXPERIMENTS} — "
              f"slots available: {slots_available}")

        if slots_available <= 0:
            print("[apply] Quota cap reached — no new experiments can be added.")
            print("[apply] Run --status to review active experiments.")
            active = _get_active_experiments(conn)
            _write_temp_yaml(active, path=args.yaml_path, dry_run=dry_run)
            return

        # Step 4: Load candidate selection
        # Import inline to avoid circular dependencies
        project_root = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(project_root))
        from scripts.select_emerging_query_candidates import select_candidates

        candidates = select_candidates(
            conn,
            limit=min(args.limit, slots_available),
            min_channels=args.min_channels,
            days=args.days,
        )

        # Filter: only add_to_experiments and not blocklisted
        approved = [
            c for c in candidates
            if c["recommended_action"] == "add_to_experiments"
            and c["normalized_text"] not in _BLOCKLIST
        ]

        print(f"[apply] Candidates approved for experiment: {len(approved)}")
        if not approved:
            print("[apply] No new candidates to add.")
            active = _get_active_experiments(conn)
            _write_temp_yaml(active, path=args.yaml_path, dry_run=dry_run)
            return

        # Step 5: Insert experiments
        inserted = 0
        for cand in approved[:slots_available]:
            print(f"[apply] {'Would insert' if dry_run else 'Inserting'}: "
                  f"'{cand['display_name']}' → '{cand['recommended_query']}' "
                  f"(risk={cand['risk_level']}, score={cand['candidate_score']:.3f})")
            if not dry_run:
                ok = _insert_experiment(conn, cand, args.expiry_days)
                if ok:
                    inserted += 1
                    print(f"[apply]   ✓ Inserted")
                else:
                    print(f"[apply]   ⚠ Skipped (duplicate or error)")

        if not dry_run:
            print(f"[apply] Inserted {inserted} new experiments.")

        # Step 6: Generate temp YAML
        active = _get_active_experiments(conn)
        _write_temp_yaml(active, path=args.yaml_path, dry_run=dry_run)

        if dry_run:
            print(f"\n[apply] DRY-RUN complete. Run with --apply to write changes.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
