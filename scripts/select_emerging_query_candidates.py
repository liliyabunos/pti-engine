#!/usr/bin/env python3
"""Phase G4-E.2 — Select Emerging Query Candidates.

Reads from emerging_signals (v2, channel-aware) and fragrance_candidates,
filters noise, ranks by signal quality, and outputs a report of candidates
suitable for temporary YouTube query experiments.

This script is READ-ONLY — no DB writes.

Output: ranked report to stdout (tabular) + optional CSV save.

Usage:
    python3 scripts/select_emerging_query_candidates.py
    python3 scripts/select_emerging_query_candidates.py --limit 20
    python3 scripts/select_emerging_query_candidates.py --min-channels 2 --days 14
    python3 scripts/select_emerging_query_candidates.py --output-csv candidates_g4e.csv
    python3 scripts/select_emerging_query_candidates.py --include-fragrance-candidates
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
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
# Risk classification
# ---------------------------------------------------------------------------

# Phrases that are genuine but likely already in resolver under a variant —
# experiments on these have low expected yield.
_LOW_YIELD_PREFIXES: frozenset[str] = frozenset({
    "dior", "chanel", "gucci", "versace", "givenchy", "hermes",
    "yves saint laurent", "ysl", "giorgio armani", "burberry",
    "creed", "mfk", "maison francis kurkdjian",
})

# Candidate phrases that contain weak/ambiguous tokens — classify as medium risk
_WEAK_TOKENS: frozenset[str] = frozenset({
    "best", "top", "great", "good", "amazing", "perfect",
    "review", "unboxing", "haul", "collection", "try",
    "affordable", "cheap", "expensive", "luxury",
    "my", "your", "our", "new", "latest",
})

# Phrases strongly associated with niche fragrance discovery — classify as low risk
_NICHE_SIGNALS: frozenset[str] = frozenset({
    "lattafa", "afnan", "rasasi", "armaf", "khadlaj", "swiss arabian",
    "al haramain", "ajmal", "arabian oud", "maison alhambra",
    "xerjoff", "nishane", "tiziana terenzi", "bdk parfums",
    "initio", "amouage", "roja parfums",
})

# Noise — candidates that look like emerging signals but are generic content
_NOISE_PATTERNS: list[re.Pattern] = [
    re.compile(r"^\d+\s+(best|top|cheap|affordable)", re.I),
    re.compile(r"how (to|do)\b", re.I),
    re.compile(r"\b(for (men|women|him|her))\s*$", re.I),
    re.compile(r"^\s*(the\s+)?(best|top)\s+\w+\s+fragrance", re.I),
]


def _normalize(text: str) -> str:
    """Minimal normalization — lowercase, collapse spaces."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _classify_risk(
    normalized: str,
    distinct_channels: int,
    candidate_score: float,
) -> str:
    """Return 'low' | 'medium' | 'high' risk level for experimenting with this candidate."""
    # Noise patterns → always high risk
    for pat in _NOISE_PATTERNS:
        if pat.search(normalized):
            return "high"

    words = set(normalized.split())

    # Contains weak tokens → medium risk floor
    if words & _WEAK_TOKENS:
        return "high"

    # Known niche signals → low risk
    for signal in _NICHE_SIGNALS:
        if signal in normalized:
            return "low"

    # Low-yield (major brands likely in resolver) → medium
    for prefix in _LOW_YIELD_PREFIXES:
        if normalized.startswith(prefix):
            return "medium"

    # Multi-channel + good score → low risk
    if distinct_channels >= 3 and candidate_score >= 4.0:
        return "low"

    if distinct_channels >= 2 and candidate_score >= 2.0:
        return "medium"

    return "high"


def _build_query(candidate_text: str) -> str:
    """Build a YouTube search query from a candidate phrase.

    Strategy: use the candidate as the core query + 'perfume fragrance review'
    suffix to target fragrance content specifically.
    """
    base = candidate_text.strip()
    # If name already contains fragrance indicator, don't double-add
    for indicator in ("perfume", "fragrance", "cologne", "parfum", "edp", "edt"):
        if indicator in base.lower():
            return base
    return f"{base} perfume review"


def _recommended_action(risk: str, distinct_channels: int) -> str:
    if risk == "low":
        return "add_to_experiments"
    if risk == "medium" and distinct_channels >= 3:
        return "add_to_experiments"
    if risk == "medium":
        return "review_first"
    return "skip"


# ---------------------------------------------------------------------------
# DB queries
# ---------------------------------------------------------------------------

def _load_emerging_signals(conn, min_channels: int, days: int, limit: int) -> List[Dict]:
    """Load top candidates from emerging_signals table."""
    sql = """
        SELECT
            id,
            display_name,
            normalized_text,
            candidate_type,
            emerging_score,
            weighted_channel_score,
            distinct_channels_count,
            total_mentions,
            top_channel_title,
            top_channel_tier,
            first_seen,
            last_seen,
            days_active,
            is_in_resolver,
            is_in_entity_market,
            review_status
        FROM emerging_signals
        WHERE is_in_resolver = FALSE
          AND is_in_entity_market = FALSE
          AND review_status != 'rejected'
          AND distinct_channels_count >= %(min_channels)s
          AND last_seen >= NOW() - INTERVAL '1 day' * %(days)s
        ORDER BY emerging_score DESC, distinct_channels_count DESC
        LIMIT %(limit)s
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, {"min_channels": min_channels, "days": days, "limit": limit * 3})
        return [dict(r) for r in cur.fetchall()]


def _load_fragrance_candidates(conn, min_occurrences: int, days: int, limit: int) -> List[Dict]:
    """Load top candidates from fragrance_candidates table."""
    sql = """
        SELECT
            id,
            normalized_text,
            candidate_type,
            occurrences,
            confidence_score,
            COALESCE(distinct_sources_count, 1) AS distinct_sources_count,
            first_seen,
            last_seen,
            validation_status
        FROM fragrance_candidates
        WHERE validation_status = 'accepted_rule_based'
          AND review_status != 'rejected_final'
          AND occurrences >= %(min_occ)s
          AND last_seen >= NOW() - INTERVAL '1 day' * %(days)s
        ORDER BY confidence_score DESC, occurrences DESC
        LIMIT %(limit)s
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, {"min_occ": min_occurrences, "days": days, "limit": limit * 3})
        return [dict(r) for r in cur.fetchall()]


def _load_existing_experiments(conn) -> set[str]:
    """Return set of normalized_candidate already in youtube_query_experiments."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT normalized_candidate FROM youtube_query_experiments "
                "WHERE status NOT IN ('suppressed', 'expired')"
            )
            return {row[0] for row in cur.fetchall()}
    except Exception:
        return set()


def _is_in_resolver(conn, normalized: str) -> bool:
    """Check if normalized text matches any resolver alias."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM resolver_aliases WHERE normalized_alias_text = %s LIMIT 1",
                (normalized,)
            )
            return cur.fetchone() is not None
    except Exception:
        return False


def _is_in_entity_market(conn, normalized: str) -> bool:
    """Check if normalized text matches any entity_market canonical_name."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM entity_market WHERE LOWER(canonical_name) = %s LIMIT 1",
                (normalized,)
            )
            return cur.fetchone() is not None
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Main selection logic
# ---------------------------------------------------------------------------

def select_candidates(
    conn,
    *,
    limit: int = 20,
    min_channels: int = 2,
    days: int = 14,
    include_fragrance_candidates: bool = False,
    min_candidate_occurrences: int = 5,
) -> List[Dict]:
    """Return ranked list of experiment candidates with metadata."""
    existing = _load_existing_experiments(conn)

    # Track A: emerging_signals (channel-aware, title-first)
    emerging = _load_emerging_signals(conn, min_channels=min_channels, days=days, limit=limit)

    rows: List[Dict] = []
    seen_normalized: set[str] = set()

    for em in emerging:
        normalized = em["normalized_text"]
        if normalized in existing or normalized in seen_normalized:
            continue
        if em.get("is_in_resolver") or em.get("is_in_entity_market"):
            continue

        risk = _classify_risk(
            normalized,
            em.get("distinct_channels_count", 0),
            em.get("emerging_score", 0.0),
        )
        action = _recommended_action(risk, em.get("distinct_channels_count", 0))
        query = _build_query(em["display_name"])

        rows.append({
            "candidate_id": em["id"],
            "source": "emerging_signals",
            "display_name": em["display_name"],
            "normalized_text": normalized,
            "candidate_type": em.get("candidate_type", "unknown"),
            "candidate_score": round(em.get("emerging_score", 0.0), 3),
            "distinct_channels": em.get("distinct_channels_count", 0),
            "total_mentions": em.get("total_mentions", 0),
            "top_channel": em.get("top_channel_title", ""),
            "top_channel_tier": em.get("top_channel_tier", ""),
            "days_active": em.get("days_active", 0),
            "is_in_resolver": False,
            "is_in_entity_market": False,
            "recommended_query": query,
            "risk_level": risk,
            "recommended_action": action,
        })
        seen_normalized.add(normalized)

        if len(rows) >= limit:
            break

    # Track B: fragrance_candidates (broader, multi-source)
    if include_fragrance_candidates and len(rows) < limit:
        candidates = _load_fragrance_candidates(
            conn,
            min_occurrences=min_candidate_occurrences,
            days=days,
            limit=limit,
        )
        for cand in candidates:
            normalized = _normalize(cand["normalized_text"])
            if normalized in existing or normalized in seen_normalized:
                continue
            # Re-check resolver and entity_market for fragrance_candidates
            if _is_in_resolver(conn, normalized) or _is_in_entity_market(conn, normalized):
                continue

            risk = _classify_risk(
                normalized,
                cand.get("distinct_sources_count", 1),
                float(cand.get("confidence_score") or 0.0),
            )
            action = _recommended_action(risk, cand.get("distinct_sources_count", 1))
            # Build display name: title-case the normalized text
            display = " ".join(w.capitalize() for w in normalized.split())
            query = _build_query(display)

            rows.append({
                "candidate_id": cand["id"],
                "source": "fragrance_candidates",
                "display_name": display,
                "normalized_text": normalized,
                "candidate_type": cand.get("candidate_type", "unknown"),
                "candidate_score": round(float(cand.get("confidence_score") or 0.0), 3),
                "distinct_channels": cand.get("distinct_sources_count", 1),
                "total_mentions": cand.get("occurrences", 0),
                "top_channel": "",
                "top_channel_tier": "",
                "days_active": 0,
                "is_in_resolver": False,
                "is_in_entity_market": False,
                "recommended_query": query,
                "risk_level": risk,
                "recommended_action": action,
            })
            seen_normalized.add(normalized)

            if len(rows) >= limit:
                break

    return rows


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _print_table(rows: List[Dict]) -> None:
    if not rows:
        print("No candidates found matching filters.")
        return

    header = (
        f"{'#':>3}  {'Display Name':<40}  {'Type':<10}  "
        f"{'Score':>6}  {'Nch':>4}  {'Risk':<6}  {'Action':<20}  {'Query'}"
    )
    print(header)
    print("-" * len(header))
    for i, r in enumerate(rows, 1):
        name = r["display_name"][:39]
        ctype = (r["candidate_type"] or "unknown")[:10]
        score = f"{r['candidate_score']:.3f}"
        nch = str(r["distinct_channels"])
        risk = r["risk_level"]
        action = r["recommended_action"][:20]
        query = r["recommended_query"][:50]
        print(f"{i:>3}  {name:<40}  {ctype:<10}  {score:>6}  {nch:>4}  {risk:<6}  {action:<20}  {query}")


def _save_csv(rows: List[Dict], path: str) -> None:
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n[select] Saved {len(rows)} candidates to {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase G4-E.2 — Select emerging candidates for targeted YouTube experiments"
    )
    parser.add_argument("--limit", type=int, default=20, help="Max candidates to return (default: 20)")
    parser.add_argument("--min-channels", type=int, default=2, help="Min distinct channels for emerging_signals (default: 2)")
    parser.add_argument("--days", type=int, default=14, help="Lookback window in days (default: 14)")
    parser.add_argument(
        "--include-fragrance-candidates",
        action="store_true",
        default=False,
        help="Also draw from fragrance_candidates table (broader, noisier pool)",
    )
    parser.add_argument("--min-candidate-occurrences", type=int, default=5,
                        help="Min occurrences for fragrance_candidates (default: 5)")
    parser.add_argument("--output-csv", type=str, default=None, help="Save results to CSV file")
    parser.add_argument("--json", action="store_true", default=False, help="Output JSON instead of table")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("[select] ERROR: DATABASE_URL is required. This script reads from production PostgreSQL.", file=sys.stderr)
        sys.exit(1)

    if not HAS_PSYCOPG2:
        print("[select] ERROR: psycopg2 is required. pip install psycopg2-binary", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(database_url)
    try:
        print(f"[select] Selecting emerging query candidates (min_channels={args.min_channels}, days={args.days}, limit={args.limit})")
        rows = select_candidates(
            conn,
            limit=args.limit,
            min_channels=args.min_channels,
            days=args.days,
            include_fragrance_candidates=args.include_fragrance_candidates,
            min_candidate_occurrences=args.min_candidate_occurrences,
        )

        # Summary by action
        by_action: dict[str, int] = {}
        for r in rows:
            by_action[r["recommended_action"]] = by_action.get(r["recommended_action"], 0) + 1

        print(f"[select] Candidates found: {len(rows)}")
        for action, count in sorted(by_action.items()):
            print(f"[select]   {action}: {count}")
        print()

        if args.json:
            print(json.dumps(rows, indent=2, default=str))
        else:
            _print_table(rows)

        if args.output_csv:
            _save_csv(rows, args.output_csv)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
