"""SIG-ID1 — Harvest Unresolved Brand-Qualified Signal Candidates.

Reads unresolved_mentions_json from resolved_signals, identifies phrases
that contain a token matching a known brand in resolver_brands, and upserts
them into unresolved_signal_candidates for operator visibility.

This makes the previously-dead unresolved_mentions_json layer observable —
surfacing Class 2 (Wrong Identity) and Class 3 (Missing Identity) failures
where real brand-qualified product names appear in content but have no alias.

Primary use case:
    "vertus amber elixir" in content → brand_token="vertus" → surfaced for
    operator review, even though Vertus Amber Elixir is absent from the catalog.

Idempotency design (full-history recompute with SET):
    Each run scans ALL resolved_signals (no date window for count computation).
    Counts are always the authoritative total from source data, never accumulated.
    Upsert uses SET occurrence_count = EXCLUDED.occurrence_count — deterministic
    overwrite, not additive.  Running the harvest twice produces identical DB state.

    OLD (broken): ON CONFLICT DO UPDATE SET count = existing + EXCLUDED  ← additive
    NEW (correct): ON CONFLICT DO UPDATE SET count = EXCLUDED.count      ← recompute

    The --days flag is optional for development/testing (limits RS rows scanned).
    Pipeline default: no --days flag → always scans full history.

Usage:
    python3 scripts/harvest_unresolved_brand_signals.py              # dry-run
    python3 scripts/harvest_unresolved_brand_signals.py --apply      # write to DB
    python3 scripts/harvest_unresolved_brand_signals.py --days 7     # dev/test: recent rows
    python3 scripts/harvest_unresolved_brand_signals.py --apply --days 7   # dev/test write

Pipeline integration:
    Called from start_pipeline.sh and start_pipeline_evening.sh with --apply only.
    No --days flag in production — always recomputes from full history.

Filtering (SIG-ID1A — Signal Candidate Queue Quality Calibration):
    --min-occurrences N (default 2): suppress single-occurrence noise
    Phrases already in resolver_aliases (already resolved) are excluded.
    Phrases in _BLOCKED_SINGLE_WORD_ALIASES, _BLOCKED_MULTI_TOKEN_PHRASES,
    or _AMBIGUOUS_PHRASE_GUARD are excluded (already guarded).
    _SKIP_TOKENS (extended): generic plural brand tokens (fragrances, perfumes,
        scents, colognes) excluded from brand_token_map — eliminates top-400
        garbage candidates (Alexandria Fragrances, Rook Perfumes, Arts&Scents).
    _HARVEST_CONTEXT_SKIP_TOKENS: brand tokens that are generic English words
        (people, little, curious, luxury, floral, elixir…) — skipped as brand
        anchors within _compute_candidates even if present in brand_token_map.
    _TRAILING_STOP_WORDS: phrases ending in a stop word are sentence fragments
        ("fragrances that", "perfumes for", "scents i") — excluded.
    Single-token filter: bare brand names with no product qualifier excluded.
    Brand-name-only filter: phrase == normalized brand name → excluded.
    Minimum-distinctiveness filter (SIG-ID1A filter 5): after removing bridge
        words (_BRIDGE_WORDS), _SKIP_TOKENS, and _HARVEST_CONTEXT_SKIP_TOKENS
        from phrase, if remaining tokens ⊆ brand name tokens → excluded.
        Catches: "paul gaultier" ⊆ Jean Paul Gaultier, "maison francis" ⊆ MFK,
        "saint laurent" ⊆ YSL, "by lattafa" → {"lattafa"} ⊆ {"lattafa"},
        "de chanel" → {"chanel"} ⊆ {"chanel"}, "louis vuitton" ⊆ Louis Vuitton.

OPS-EE1: Full-history recompute chosen over incremental accumulation.
    RS table at ~30K rows and growing ~60-100/day; full scan is fast (< 2s).
    Incremental accumulation is cheaper per-run but structurally incorrect:
    overlapping day windows silently inflate counts, making the operator queue
    unreliable. Correctness > micro-optimization here.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
_log = logging.getLogger(__name__)

# Brand token minimum length — matches pg_resolver_store.get_brand_token_map()
_MIN_TOKEN_LEN = 6

# Tokens excluded when building brand_token_map from resolver_brands.
# Extended in SIG-ID1A to include plural forms that dominated the queue
# (Alexandria Fragrances → "fragrances", Rook Perfumes → "perfumes", etc.)
_SKIP_TOKENS: frozenset = frozenset({
    "parfum", "perfume", "cologne", "scent", "fragrance",
    "extrait", "parfums", "maison", "collection", "edition",
    # SIG-ID1A additions — plural forms excluded (same rationale as singular)
    "fragrances", "perfumes", "scents", "colognes",
})

# Brand tokens too generic to serve as meaningful brand anchors in the harvest.
# These tokens ARE valid brand identifiers (e.g. "signature" → Signature Royale,
# "little" → Little and Grim) but produce enormous noise because they are common
# English words that appear constantly in fragrance discourse.
# Applied within _compute_candidates — skips (phrase, token) pairs where the
# anchor token is in this set, even if the token is in brand_token_map.
_HARVEST_CONTEXT_SKIP_TOKENS: frozenset = frozenset({
    # Generic common words that happen to be brand names
    "people", "little", "curious", "sample", "luxury", "create", "different",
    "signature", "select", "unique", "classic", "divine", "beautiful",
    # Geographic / language / nationality words
    "avenue", "french", "london", "grande",
    # Fragrance category / olfactory descriptors
    "floral", "incense", "gourmand", "orange", "natural",
    # Retail / commercial descriptors
    "beauty", "fashion", "purchase", "sephora", "prestige",
    # Note/ingredient term (also a brand: Elixir Attar) — produces "le male elixir",
    # "male elixir", "nocturno elixir" attributed to Elixir Attar instead of JPG
    "elixir",
    # Geographic brand component ("Swiss Arabian" → "arabian" maps to Arabian Oud)
    "arabian",
})

# Prepositions and function words that appear in brand/product phrases as connectors
# but carry no product-qualifying meaning on their own.
# Used in the minimum-distinctiveness check: after removing bridge words + skip tokens
# from a phrase, if remaining tokens ⊆ brand name tokens → sentence fragment.
# Examples: "by lattafa" → by=bridge → {"lattafa"} ⊆ {"lattafa"} → filtered.
#           "de chanel"  → de=bridge → {"chanel"} ⊆ {"chanel"} → filtered.
#           "paul gaultier" → {"paul", "gaultier"} ⊆ {"jean","paul","gaultier"} → filtered.
_BRIDGE_WORDS: frozenset = frozenset({
    "by", "from", "de", "du", "di", "le", "la", "les",
    "for", "per", "con", "von", "al", "l",
    "and", "of", "in", "the",
})

# Phrases ending in these words are sentence fragments extracted from continuous
# text, not product names.  Examples: "fragrances that", "perfumes for", "scents i".
_TRAILING_STOP_WORDS: frozenset = frozenset({
    "that", "for", "are", "in", "from", "and", "or", "but", "with",
    "of", "to", "i", "a", "at", "on", "you", "they", "we", "it",
    "by", "he", "she", "is", "this", "these", "my", "our", "your",
    "if", "the", "que", "de", "la", "le", "les", "un", "una", "los", "las",
    "also", "some", "all", "an", "into", "about", "after", "before",
    "has", "have", "had", "be", "do", "did",
})

# Exported for tests — verifies SET semantics are intact
_UPSERT_SQL = """
    INSERT INTO unresolved_signal_candidates
        (phrase, brand_token, brand_canonical_name,
         occurrence_count, source_count, first_seen, last_seen,
         candidate_status, updated_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', now())
    ON CONFLICT (phrase, brand_token) DO UPDATE SET
        occurrence_count = EXCLUDED.occurrence_count,
        source_count     = EXCLUDED.source_count,
        last_seen        = GREATEST(unresolved_signal_candidates.last_seen, EXCLUDED.last_seen),
        first_seen       = LEAST(unresolved_signal_candidates.first_seen, EXCLUDED.first_seen),
        updated_at       = now()
"""


def _normalize(text: str) -> str:
    """Minimal normalization matching normalize_text() logic."""
    import re
    text = text.lower()
    text = re.sub(r"[''`]s?\b", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _build_brand_token_map(cur: Any) -> Dict[str, str]:
    """Build normalized brand token → canonical brand name map from resolver_brands."""
    cur.execute("SELECT canonical_name FROM resolver_brands")
    token_map: Dict[str, str] = {}
    for (canonical_name,) in cur.fetchall():
        normalized = _normalize(canonical_name)
        for token in normalized.split():
            if len(token) >= _MIN_TOKEN_LEN and token not in _SKIP_TOKENS:
                if token not in token_map:
                    token_map[token] = canonical_name
    _log.info("Brand token map: %d entries", len(token_map))
    return token_map


def _load_existing_aliases(cur: Any) -> frozenset:
    """Load all normalized alias texts already in resolver_aliases (already resolved)."""
    cur.execute(
        "SELECT normalized_alias_text FROM resolver_aliases WHERE entity_type = 'perfume'"
    )
    return frozenset(row[0] for row in cur.fetchall())


def _load_blocked_phrases() -> frozenset:
    """Import blocked phrases from perfume_resolver to exclude already-guarded phrases."""
    try:
        from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import (
            _BLOCKED_SINGLE_WORD_ALIASES,
            _BLOCKED_MULTI_TOKEN_PHRASES,
            _AMBIGUOUS_PHRASE_GUARD,
        )
        return (
            frozenset(_BLOCKED_SINGLE_WORD_ALIASES)
            | frozenset(_BLOCKED_MULTI_TOKEN_PHRASES)
            | frozenset(_AMBIGUOUS_PHRASE_GUARD.keys())
        )
    except ImportError:
        return frozenset()


def _compute_candidates(
    rs_rows: List[Tuple[Any, Any]],
    brand_token_map: Dict[str, str],
    existing_aliases: frozenset,
    blocked_phrases: frozenset,
    min_occurrences: int,
) -> Dict[Tuple[str, str], Dict]:
    """Pure function: compute candidate dict from raw RS rows.

    Returns {(phrase, brand_token): {occurrences, sources, first_date, last_date,
    brand_canonical}} filtered to min_occurrences.

    Called by harvest() and directly by tests (no DB required).
    This function is deterministic: same input → same output, always.
    """
    candidates: Dict[Tuple[str, str], Dict] = defaultdict(
        lambda: {"occurrences": 0, "sources": 0, "first_date": None, "last_date": None, "brand_canonical": ""}
    )

    for unresolved_json, rs_date in rs_rows:
        if not unresolved_json:
            continue
        try:
            phrases = (
                json.loads(unresolved_json)
                if isinstance(unresolved_json, str)
                else unresolved_json
            )
            if not isinstance(phrases, list):
                continue
        except (json.JSONDecodeError, TypeError):
            continue

        seen_in_source: Set[Tuple[str, str]] = set()
        for phrase in phrases:
            if not isinstance(phrase, str):
                continue
            norm = _normalize(phrase)
            if not norm:
                continue
            # Skip phrases already resolved (alias exists → not unresolved)
            if norm in existing_aliases:
                continue
            # Skip phrases already guarded/blocked (handled; not useful candidates)
            if norm in blocked_phrases:
                continue

            tokens = norm.split()

            # SIG-ID1A filter 1: single-token phrases are bare brand names with no
            # product qualifier — not actionable for catalog expansion or Class 3 repair.
            if len(tokens) < 2:
                continue

            # SIG-ID1A filter 2: sentence fragment — phrase ends in a stop word,
            # meaning it was extracted from continuous prose ("fragrances that").
            if tokens[-1] in _TRAILING_STOP_WORDS:
                continue

            for token in tokens:
                if token not in brand_token_map:
                    continue

                # SIG-ID1A filter 3: skip generic-word brand anchors — tokens that
                # are common English words even though a brand happens to use them.
                if token in _HARVEST_CONTEXT_SKIP_TOKENS:
                    continue

                brand_canonical = brand_token_map[token]

                # SIG-ID1A filter 4: brand-name-only phrase — the entire phrase is
                # just the normalized brand name with no product qualifier.
                # Examples: "jean paul gaultier", "dolce gabbana", "giorgio armani".
                if norm == _normalize(brand_canonical):
                    continue

                # SIG-ID1A filter 5: minimum-distinctiveness check.
                # After removing bridge words, skip tokens, and context-skip tokens
                # from the phrase, if the remaining tokens are a subset of the brand
                # name tokens, the phrase adds no product qualifier.
                # Catches partial brand names like "paul gaultier" ⊆ "jean paul gaultier",
                # "maison francis" ⊆ "maison francis kurkdjian", "saint laurent" ⊆
                # "yves saint laurent", "by lattafa" → {"lattafa"} ⊆ {"lattafa"}.
                # Note: _HARVEST_CONTEXT_SKIP_TOKENS NOT included — those tokens can be
                # genuine product qualifiers (e.g. "arabiyat prestige" → "prestige" IS a
                # product qualifier when brand is "Arabiyat").  Only bridge words and
                # generic category suffixes (_SKIP_TOKENS) are stripped.
                _all_skip = _BRIDGE_WORDS | _SKIP_TOKENS
                distinctive_tokens = {t for t in tokens if t not in _all_skip}
                brand_name_tokens = set(_normalize(brand_canonical).split())
                if distinctive_tokens and distinctive_tokens.issubset(brand_name_tokens):
                    continue

                key = (norm, token)
                rec = candidates[key]
                rec["occurrences"] += 1
                rec["brand_canonical"] = brand_canonical
                if rs_date and (rec["first_date"] is None or rs_date < rec["first_date"]):
                    rec["first_date"] = rs_date
                if rs_date and (rec["last_date"] is None or rs_date > rec["last_date"]):
                    rec["last_date"] = rs_date
                # source_count: count distinct RS rows (one per content item)
                if key not in seen_in_source:
                    seen_in_source.add(key)
                    rec["sources"] += 1


    return {k: v for k, v in candidates.items() if v["occurrences"] >= min_occurrences}


def harvest(
    cur: Any,
    *,
    days: Optional[int] = None,
    min_occurrences: int,
    apply: bool,
) -> Dict:
    """Main harvest logic.

    days=None (default): scan ALL resolved_signals — authoritative full-history counts.
    days=N: limit RS scan to created_at >= now() - N days (development/testing only).

    Idempotency: guaranteed because _compute_candidates() is deterministic and the
    upsert uses SET semantics (overwrite with freshly computed value, not accumulate).
    """
    brand_token_map = _build_brand_token_map(cur)
    existing_aliases = _load_existing_aliases(cur)
    blocked_phrases = _load_blocked_phrases()

    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        _log.info("Loading resolved_signals since %s (dev/test mode)...", cutoff.date())
        cur.execute(
            """
            SELECT rs.unresolved_mentions_json, rs.created_at::date AS rs_date
            FROM resolved_signals rs
            WHERE rs.unresolved_mentions_json IS NOT NULL
              AND rs.created_at >= %s
            """,
            (cutoff,),
        )
    else:
        _log.info("Loading all resolved_signals (full-history recompute)...")
        cur.execute(
            """
            SELECT rs.unresolved_mentions_json, rs.created_at::date AS rs_date
            FROM resolved_signals rs
            WHERE rs.unresolved_mentions_json IS NOT NULL
            """
        )

    rs_rows = cur.fetchall()
    _log.info("Processing %d RS rows...", len(rs_rows))

    qualifying = _compute_candidates(
        rs_rows, brand_token_map, existing_aliases, blocked_phrases, min_occurrences
    )

    # Sort by occurrence count for logging
    sorted_candidates = sorted(
        qualifying.items(), key=lambda x: x[1]["occurrences"], reverse=True
    )

    print(f"\n=== Top candidates (>= {min_occurrences} occurrences) ===")
    for i, ((phrase, brand_token), rec) in enumerate(sorted_candidates[:20]):
        print(
            f"  [{i+1:2d}] '{phrase}' | brand_token='{brand_token}' "
            f"| brand='{rec['brand_canonical']}' | occurrences={rec['occurrences']} "
            f"| sources={rec['sources']} | last={rec['last_date']}"
        )
    if len(sorted_candidates) > 20:
        print(f"  ... and {len(sorted_candidates) - 20} more")

    upserted = 0

    if apply and qualifying:
        today = date.today()
        for (phrase, brand_token), rec in qualifying.items():
            first_seen = rec["first_date"] or today
            last_seen = rec["last_date"] or today
            cur.execute(
                _UPSERT_SQL,
                (
                    phrase,
                    brand_token,
                    rec["brand_canonical"],
                    rec["occurrences"],
                    rec["sources"],
                    first_seen,
                    last_seen,
                ),
            )
            upserted += 1

    print(f"\n=== Summary ===")
    print(f"  RS rows processed: {len(rs_rows)}")
    print(f"  Unique candidates found (all occurrences): {len(qualifying) + len([k for k, v in _compute_candidates(rs_rows, brand_token_map, existing_aliases, blocked_phrases, 1).items() if v['occurrences'] < min_occurrences])}")
    print(f"  Qualifying (>= {min_occurrences} occurrences): {len(qualifying)}")
    if apply:
        print(f"  Upserted (SET): {upserted}")
    else:
        print(f"  Dry-run — no changes committed.")

    return {
        "rs_rows_processed": len(rs_rows),
        "qualifying": len(qualifying),
        "upserted": upserted if apply else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="SIG-ID1 Unresolved Brand Signal Harvest")
    parser.add_argument(
        "--apply", action="store_true",
        help="Write to DB (default: dry-run)",
    )
    parser.add_argument(
        "--days", type=int, default=None,
        help="Limit RS scan to N days (default: full history — recommended for production)",
    )
    parser.add_argument(
        "--min-occurrences", type=int, default=2,
        help="Minimum occurrence count (default 2)",
    )
    args = parser.parse_args()

    import os
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    cur = conn.cursor()

    scope = f"days={args.days}" if args.days else "full history"
    print(f"=== SIG-ID1 Unresolved Brand Signal Harvest {'APPLY' if args.apply else 'DRY-RUN'} ===")
    print(f"    scope={scope}, min_occurrences={args.min_occurrences}")

    harvest(
        cur,
        days=args.days,
        min_occurrences=args.min_occurrences,
        apply=args.apply,
    )

    if args.apply:
        conn.commit()
        print("\nCommitted.")
    else:
        conn.rollback()
        print("\nDry-run — no changes committed.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
