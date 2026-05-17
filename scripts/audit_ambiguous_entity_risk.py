#!/usr/bin/env python3
"""
RES-AMB-GLOBAL — Systemic Ambiguous Entity Risk Audit Framework
================================================================

Scores every market-relevant perfume entity for ambiguity / false-positive
risk across 5 explainable dimensions and emits a ranked report.

Dimensions (each 0.0 = no risk, 1.0 = maximum risk):
  D1  Name Language          — is the canonical_name a common English phrase?
  D2  Mention Shape          — are total mentions suspiciously thin / concentrated?
  D3  RS Integrity           — does the RS-matched text contain brand context?
  D4  Topic Coherence        — do entity topics look like real fragrance discourse?
  D5  Brand Obscurity        — is the brand well-known in the fragrance corpus?

Composite risk = weighted sum (D1×0.35 + D2×0.25 + D3×0.25 + D4×0.10 + D5×0.05)

Recommended action:
  A  risk >= 0.72  →  Investigate immediately — likely false positive
  B  risk >= 0.52  →  Add to _AMBIGUOUS_PHRASE_GUARD or _BLOCKED_*
  C  risk >= 0.32  →  Monitor — worth watching on next pipeline run
  D  risk <  0.32  →  Likely clean

Usage:
  python3 scripts/audit_ambiguous_entity_risk.py --scope active-today
  python3 scripts/audit_ambiguous_entity_risk.py --scope recent-movers
  python3 scripts/audit_ambiguous_entity_risk.py --scope tracked-market
  python3 scripts/audit_ambiguous_entity_risk.py --scope active-today --min-risk 0.52
  python3 scripts/audit_ambiguous_entity_risk.py --scope active-today --output report.json
  python3 scripts/audit_ambiguous_entity_risk.py --scope active-today --csv report.csv
  python3 scripts/audit_ambiguous_entity_risk.py --calibrate   # sanity-check known entities

Environment:
  DATABASE_URL  — PostgreSQL connection string (required for production)
  PTI_DB_PATH   — SQLite dev path (used if DATABASE_URL absent)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Common English word corpus — words that SHOULD NOT appear alone as reliable
# brand/product anchors.  Derived from the RES-AMB1/2/3 false-positive series
# plus standard English function/evaluative words.
# ---------------------------------------------------------------------------
_COMMON_ENGLISH_WORDS: frozenset = frozenset({
    # RES-AMB confirmed triggers
    "very", "well", "so", "happy", "too", "feminine", "true", "icon",
    "first", "class", "i", "am", "right", "now", "scent", "of",
    "blue", "peace", "love", "you", "are", "en", "route", "good",
    "vibes", "one", "only", "and", "the", "a", "an",
    # Auxiliary / modal verbs — common in everyday speech, NOT product-name anchors
    # Bug fix: "will" was missing, causing "I will" to score D1=0.57 instead of 0.85
    "will", "can", "would", "could", "should", "might", "may", "shall",
    "have", "has", "had", "be", "been", "being", "do", "did", "does",
    "is", "was", "were", "get", "got", "let", "make", "made",
    # Common pronouns / determiners
    "it", "its", "we", "us", "they", "them", "their", "those", "these",
    "who", "what", "when", "where", "how", "which", "then", "here", "there",
    "some", "all", "each", "any", "both", "few", "many", "much",
    # Adjectives / descriptors that appear in product names AND common speech
    "light", "dark", "pure", "deep", "rich", "soft", "warm", "cool",
    "fresh", "green", "white", "black", "red", "pink", "gold", "silver",
    "sweet", "dry", "clean", "bold", "wild", "free", "new", "old",
    "young", "strong", "secret", "desire", "passion", "dream", "night",
    "day", "summer", "winter", "spring", "forever", "always", "never",
    "still", "natural", "pure", "rare", "unique", "intense", "extreme",
    "hot", "sexy", "men", "woman", "women", "man", "girl", "boy",
    "by", "for", "in", "my", "our", "your", "her", "his",
    "this", "that", "not", "no", "yes", "just", "more", "less",
    "best", "great", "perfect", "amazing", "beautiful", "lovely",
    "classic", "modern", "original", "special", "limited", "exclusive",
    "active", "energy", "power", "force", "life", "love", "time",
    "star", "sun", "moon", "rose", "iris", "lily", "violet", "jasmine",
    "musk", "oud", "amber", "cedar", "wood", "smoke", "earth",
    # Evaluative
    "nice", "fine", "ok", "okay", "pretty", "quite",
    "super", "ultra", "mega", "mini", "micro",
})

# Fragrance-specific tokens that strongly LOWER risk (genuine product names
# use these; common speech rarely does).
_FRAGRANCE_SPECIFIC_TOKENS: frozenset = frozenset({
    "eau", "parfum", "toilette", "cologne", "extrait", "elixir",
    "edp", "edt", "edc", "intense", "concentree", "absolu", "noir",
    "bleu", "pour", "homme", "femme", "oud", "attar", "khalis",
    "maison", "exclusif", "collection", "signature",
})

# Known anchor brands in the fragrance corpus — brand token presence strongly
# lowers RS-integrity risk.  Keep this minimal; we're checking corpus presence
# not brand prestige.
_WELL_KNOWN_BRAND_TOKENS: frozenset = frozenset({
    "creed", "chanel", "dior", "gucci", "armani", "ysl", "lancome",
    "givenchy", "versace", "prada", "hermes", "burberry", "cartier",
    "bvlgari", "montblanc", "davidoff", "lacoste", "hugo", "boss",
    "tom", "ford", "maison", "margiela", "byredo", "diptyque",
    "jo", "malone", "penhaligons", "parfums", "marly", "frederic",
    "malle", "escentric", "molecules", "initio", "kilian", "xerjoff",
    "lattafa", "rasasi", "ajmal", "armaf", "kayali", "baccarat",
    "kurkdjian", "amouage", "roja", "dove", "moresque", "nishane",
    "memo", "serge", "lutens", "l'artisan", "acqua", "parma",
    "comme", "garcons", "issey", "miyake", "azzaro", "mugler",
})


def _normalize(text: str) -> str:
    """Strip accents, lower-case, keep only word chars and spaces."""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_only = nfkd.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-z0-9\s]", " ", ascii_only.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _tokens(text: str) -> List[str]:
    return _normalize(text).split()


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DimensionScores:
    name_language: float    # D1
    mention_shape: float    # D2
    rs_integrity: float     # D3
    topic_coherence: float  # D4
    brand_obscurity: float  # D5


@dataclass
class EntityRiskResult:
    entity_id: str          # UUID
    canonical_name: str
    brand_name: str
    composite_risk: float
    action: str             # A / B / C / D
    d1_name_language: float
    d2_mention_shape: float
    d3_rs_integrity: float
    d4_topic_coherence: float
    d5_brand_obscurity: float
    # Evidence
    total_mentions: float
    active_dates: int
    max_daily_mentions: float
    rs_sample_brand_hit_rate: float   # fraction of RS matches where brand token present
    rs_sample_count: int
    fragrance_topic_count: int
    already_guarded: bool
    evidence_note: str


# ---------------------------------------------------------------------------
# Risk dimension scorers
# ---------------------------------------------------------------------------

def score_d1_name_language(canonical_name: str, brand_name: str) -> Tuple[float, str]:
    """
    How 'ordinary' is the canonical_name?
    High risk: short common-English phrases with no fragrance tokens.
    Low risk: distinctive multi-token names, non-ASCII, fragrance tokens present.
    """
    norm = _normalize(canonical_name)
    toks = _tokens(canonical_name)
    n = len(toks)

    # Fragrance tokens strongly lower risk
    has_fragrance_token = any(t in _FRAGRANCE_SPECIFIC_TOKENS for t in toks)
    if has_fragrance_token:
        return 0.05, "has fragrance-specific token"

    # Non-ASCII originals signal a proper foreign brand name → lower risk
    if any(ord(c) > 127 for c in canonical_name):
        return 0.10, "contains non-ASCII (foreign brand name)"

    # Count how many tokens are common English words
    common_count = sum(1 for t in toks if t in _COMMON_ENGLISH_WORDS)
    common_ratio = common_count / n if n else 0.0

    # Single-token names: already blocked by _BLOCKED_SINGLE_WORD_ALIASES for known cases
    # but unblocked single common words are still high risk
    if n == 1:
        score = 0.85 if toks[0] in _COMMON_ENGLISH_WORDS else 0.25
        return score, f"single token — {'common word' if score > 0.5 else 'distinctive'}"

    if n == 2:
        # 2-token names: risk scales with common_ratio
        score = 0.30 + (common_ratio * 0.55)  # 0.30 – 0.85 range
        note = f"2-token ({common_count}/{n} common words)"
        return round(score, 3), note

    if n == 3:
        score = 0.10 + (common_ratio * 0.55)  # 0.10 – 0.65 range
        note = f"3-token ({common_count}/{n} common words)"
        return round(score, 3), note

    # 4+ tokens: lower baseline risk, but still scale with common_ratio
    score = 0.05 + (common_ratio * 0.40)
    return round(score, 3), f"{n}-token ({common_count}/{n} common words)"


def score_d2_mention_shape(
    total_mentions: float,
    active_dates: int,
    max_daily_mentions: float,
) -> Tuple[float, str]:
    """
    Thin/concentrated mention patterns suggest a fragile signal.
    False positives tend to have very few total mentions and very few distinct dates.
    """
    if total_mentions <= 0:
        return 0.90, "zero mentions"

    # Total mentions risk
    if total_mentions <= 3:
        total_risk = 0.90
    elif total_mentions <= 10:
        total_risk = 0.70
    elif total_mentions <= 25:
        total_risk = 0.45
    elif total_mentions <= 50:
        total_risk = 0.25
    else:
        total_risk = max(0.05, 0.25 - (total_mentions - 50) / 500)

    # Active dates risk
    if active_dates <= 1:
        date_risk = 0.85
    elif active_dates <= 3:
        date_risk = 0.60
    elif active_dates <= 7:
        date_risk = 0.35
    else:
        date_risk = max(0.05, 0.35 - (active_dates - 7) / 70)

    # Max daily mentions (very low max = suspicious)
    if max_daily_mentions <= 1.0:
        max_risk = 0.80
    elif max_daily_mentions <= 3.0:
        max_risk = 0.50
    else:
        max_risk = max(0.05, 0.50 - (max_daily_mentions - 3) / 20)

    score = total_risk * 0.45 + date_risk * 0.35 + max_risk * 0.20

    # Floor: D2 never goes below 0.15.
    # Rationale: a mature false positive that accumulates volume over many dates
    # would otherwise drive D2 near 0.0, suppressing D3's high-risk signal.
    # D2=0.15 floor means volume alone cannot offset D3 (RS integrity) evidence.
    score = max(score, 0.15)

    note = f"total={total_mentions:.1f}, dates={active_dates}, max_daily={max_daily_mentions:.1f}"
    return round(score, 3), note


def score_d3_rs_integrity(
    brand_hit_rate: float,
    rs_sample_count: int,
    brand_name: str,
) -> Tuple[float, str]:
    """
    What fraction of RS matched_from texts contain a brand token?
    Low brand presence in match context → higher risk.
    """
    if rs_sample_count == 0:
        return 0.60, "no RS rows sampled"

    # Invert: high hit_rate = low risk
    risk = 1.0 - brand_hit_rate

    # Temper if sample is small
    if rs_sample_count == 1:
        risk = 0.40 + risk * 0.45  # compress toward midpoint for tiny samples
    elif rs_sample_count <= 3:
        risk = 0.20 + risk * 0.65

    note = f"brand_hit={brand_hit_rate:.0%} of {rs_sample_count} RS matches"
    return round(min(risk, 1.0), 3), note


def score_d4_topic_coherence(
    fragrance_topic_count: int,
    total_topic_count: int,
    has_review_topic: bool,
) -> Tuple[float, str]:
    """
    Entities with rich fragrance-specific topic links are lower risk.
    Few or no fragrance topics = higher risk.
    """
    if total_topic_count == 0:
        return 0.70, "no topic links"

    if fragrance_topic_count == 0:
        return 0.65, f"0/{total_topic_count} fragrance topics"

    ratio = fragrance_topic_count / total_topic_count
    # More total topics also lowers risk (entity has been discussed a lot)
    volume_bonus = min(0.20, total_topic_count / 100)
    score = max(0.0, (1.0 - ratio) * 0.60 - volume_bonus)
    if has_review_topic:
        score = max(0.0, score - 0.15)

    note = f"frag_topics={fragrance_topic_count}/{total_topic_count}"
    return round(score, 3), note


def score_d5_brand_obscurity(brand_name: str, brand_mention_count: float) -> Tuple[float, str]:
    """
    Obscure brands are higher risk — false-positive resolver matches are more
    likely to accumulate for entities from brands the community rarely discusses.
    """
    brand_toks = _tokens(brand_name)

    # Known fragrance brands → lower risk
    if any(t in _WELL_KNOWN_BRAND_TOKENS for t in brand_toks):
        return 0.10, "known fragrance brand"

    # Brand mention volume proxy
    if brand_mention_count >= 100:
        return 0.15, f"brand mention volume={brand_mention_count:.0f}"
    elif brand_mention_count >= 20:
        return 0.30, f"brand mention volume={brand_mention_count:.0f}"
    elif brand_mention_count >= 5:
        return 0.50, f"brand mention volume={brand_mention_count:.0f}"
    else:
        return 0.75, f"brand barely mentioned ({brand_mention_count:.0f})"


def _compute_composite(d: DimensionScores) -> float:
    return (
        d.name_language   * 0.35
        + d.mention_shape * 0.25
        + d.rs_integrity  * 0.25
        + d.topic_coherence * 0.10
        + d.brand_obscurity * 0.05
    )


def _action(risk: float) -> str:
    if risk >= 0.72:
        return "A"
    if risk >= 0.52:
        return "B"
    if risk >= 0.32:
        return "C"
    return "D"


# ---------------------------------------------------------------------------
# Production data loading (bulk queries)
# ---------------------------------------------------------------------------

def _connect(db_url: str):
    """Return a psycopg2 connection."""
    import psycopg2
    return psycopg2.connect(db_url, connect_timeout=15)


_FRAGRANCE_TOPIC_KEYWORDS: frozenset = frozenset({
    "review", "fragrance", "perfume", "cologne", "scent", "oud", "floral",
    "woody", "citrus", "musk", "amber", "vanilla", "aquatic", "fresh",
    "oriental", "chypre", "fougere", "gourmand", "sillage", "longevity",
    "projection", "dupe", "clone", "alternative", "blind", "buy",
    "bottle", "sample", "decant", "split", "haul", "collection",
    "niche", "designer", "batch", "reformulation",
})


def _fetch_entity_universe(cur, scope: str) -> List[Dict]:
    """Return list of {entity_id, canonical_name, brand_name} for scope."""
    if scope == "active-today":
        date_filter = "AND etd.date >= CURRENT_DATE - 1"
    elif scope == "recent-movers":
        date_filter = "AND etd.date >= CURRENT_DATE - 7"
    else:  # tracked-market
        date_filter = ""

    sql = f"""
        SELECT DISTINCT em.id::text, em.canonical_name, COALESCE(em.brand_name, '') as brand_name
        FROM entity_market em
        JOIN entity_timeseries_daily etd ON etd.entity_id = em.id
        WHERE em.entity_type = 'perfume'
          AND etd.mention_count > 0
          {date_filter}
        ORDER BY em.canonical_name
    """
    cur.execute(sql)
    return [{"entity_id": r[0], "canonical_name": r[1], "brand_name": r[2]}
            for r in cur.fetchall()]


def _fetch_mention_shapes(cur, entity_ids: List[str]) -> Dict[str, Dict]:
    """Return per-entity mention shape stats."""
    id_list = ",".join(f"'{eid}'" for eid in entity_ids)
    cur.execute(f"""
        SELECT
            entity_id::text,
            SUM(mention_count) AS total_mentions,
            COUNT(*) FILTER (WHERE mention_count > 0) AS active_dates,
            MAX(mention_count) AS max_daily
        FROM entity_timeseries_daily
        WHERE entity_id::text IN ({id_list})
          AND entity_type = 'perfume'
        GROUP BY entity_id
    """)
    return {
        r[0]: {"total_mentions": float(r[1] or 0), "active_dates": int(r[2] or 0),
                "max_daily": float(r[3] or 0)}
        for r in cur.fetchall()
    }


def _fetch_topic_stats(cur, entity_ids: List[str]) -> Dict[str, Dict]:
    """Return per-entity topic link stats."""
    id_list = ",".join(f"'{eid}'" for eid in entity_ids)
    cur.execute(f"""
        SELECT
            entity_id::text,
            COUNT(*) AS total_topics,
            COUNT(*) FILTER (WHERE topic_type = 'topic') AS organic_topics,
            array_agg(DISTINCT topic_text) AS topic_texts
        FROM entity_topic_links
        WHERE entity_id::text IN ({id_list})
          AND entity_type = 'perfume'
        GROUP BY entity_id
    """)
    out: Dict[str, Dict] = {}
    for r in cur.fetchall():
        eid, total, organic, texts = r[0], int(r[1] or 0), int(r[2] or 0), r[3] or []
        frag_count = sum(
            1 for t in texts
            if any(kw in _normalize(t) for kw in _FRAGRANCE_TOPIC_KEYWORDS)
        )
        has_review = any("review" in _normalize(t) for t in texts)
        out[eid] = {
            "total_topics": total,
            "organic_topics": organic,
            "fragrance_topic_count": frag_count,
            "has_review_topic": has_review,
        }
    return out


def _fetch_rs_integrity(cur, entity_canonical_names: List[str]) -> Dict[str, Dict]:
    """
    For each canonical_name, sample RS matched_from texts and check whether
    brand tokens appear.  Returns per-canonical_name stats.

    Runs ONE bulk query over resolved_signals for performance.
    """
    # Build a fast lookup: canonical_name → brand tokens
    # (populated externally, passed into scoring)
    # Here we just return the raw (canonical_name → list[matched_from]) map.

    # Single bulk extract from resolved_signals
    cur.execute("""
        SELECT
            elem->>'canonical_name' AS cname,
            elem->>'matched_from'   AS matched_from
        FROM resolved_signals,
             jsonb_array_elements(resolved_entities_json::jsonb) AS elem
        WHERE elem->>'entity_type' = 'perfume'
    """)
    rows = cur.fetchall()

    # Index by canonical_name (case-sensitive from RS)
    by_name: Dict[str, List[str]] = defaultdict(list)
    for cname, mfrom in rows:
        if cname:
            by_name[cname].append(mfrom or "")
    return dict(by_name)


def _fetch_brand_mention_counts(cur, brand_names: List[str]) -> Dict[str, float]:
    """Return total entity_mentions counts per brand (entity_type='brand') as proxy."""
    cur.execute("""
        SELECT em.brand_name, SUM(etd.mention_count) as total
        FROM entity_market em
        JOIN entity_timeseries_daily etd ON etd.entity_id = em.id
        WHERE em.entity_type = 'brand'
          AND em.brand_name IS NOT NULL
        GROUP BY em.brand_name
    """)
    return {r[0]: float(r[1] or 0) for r in cur.fetchall()}


# ---------------------------------------------------------------------------
# Known guarded entities (already in resolver guards)
# ---------------------------------------------------------------------------

def _build_guarded_set() -> Set[str]:
    """Return set of normalized canonical names already guarded in the resolver."""
    guarded: Set[str] = set()
    # From _BLOCKED_SINGLE_WORD_ALIASES: these are alias tokens, not canonical names;
    # we mark as guarded if canonical_name normalizes to one of these single tokens.
    # For simplicity, mark entities whose normalized name appears in guard dicts.
    single_blocked = {
        "don", "pink", "dot", "smart", "standard", "heritage", "moth", "jack",
        "man", "two", "11", "21",
    }
    multi_blocked = {"so so", "i am so so", "so i am so so"}
    phrase_guarded = {
        "i am", "right now", "scent of", "blue oud", "peace love",
        "so you", "you are", "en route", "fragrance of summer",
        "one only", "one and only", "good vibes",
        "very well", "so happy", "too feminine", "true icon", "first class",
    }
    guarded.update(single_blocked)
    guarded.update(multi_blocked)
    guarded.update(phrase_guarded)
    return guarded


# ---------------------------------------------------------------------------
# Main scoring
# ---------------------------------------------------------------------------

def score_entity(
    entity: Dict,
    mention_shape: Dict,
    topic_stats: Dict,
    rs_by_name: Dict[str, List[str]],
    brand_mention_counts: Dict[str, float],
    guarded_set: Set[str],
) -> EntityRiskResult:
    eid = entity["entity_id"]
    cname = entity["canonical_name"]
    bname = entity["brand_name"]

    shape = mention_shape.get(eid, {"total_mentions": 0, "active_dates": 0, "max_daily": 0})
    topics = topic_stats.get(eid, {"total_topics": 0, "fragrance_topic_count": 0,
                                    "has_review_topic": False})

    # D1 — name language
    d1, d1_note = score_d1_name_language(cname, bname)

    # D2 — mention shape
    d2, d2_note = score_d2_mention_shape(
        shape["total_mentions"], shape["active_dates"], shape["max_daily"]
    )

    # D3 — RS integrity
    rs_matches = rs_by_name.get(cname, [])
    brand_toks = set(_tokens(bname)) - {""}
    if rs_matches and brand_toks:
        hits = sum(
            1 for mf in rs_matches
            if any(bt in _normalize(mf) for bt in brand_toks)
        )
        brand_hit_rate = hits / len(rs_matches)
    elif rs_matches:
        brand_hit_rate = 0.0
    else:
        brand_hit_rate = 0.0
    d3, d3_note = score_d3_rs_integrity(brand_hit_rate, len(rs_matches), bname)

    # D4 — topic coherence
    d4, d4_note = score_d4_topic_coherence(
        topics["fragrance_topic_count"], topics["total_topics"],
        topics.get("has_review_topic", False)
    )

    # D5 — brand obscurity
    brand_total_mentions = brand_mention_counts.get(bname, 0.0)
    d5, d5_note = score_d5_brand_obscurity(bname, brand_total_mentions)

    dims = DimensionScores(
        name_language=d1,
        mention_shape=d2,
        rs_integrity=d3,
        topic_coherence=d4,
        brand_obscurity=d5,
    )
    composite = round(_compute_composite(dims), 4)
    act = _action(composite)

    norm_cname = _normalize(cname)
    is_guarded = norm_cname in guarded_set

    # Build evidence note
    evidence_parts = [d1_note, d2_note, d3_note, d4_note, d5_note]
    evidence_note = " | ".join(evidence_parts)

    return EntityRiskResult(
        entity_id=eid,
        canonical_name=cname,
        brand_name=bname,
        composite_risk=composite,
        action=act,
        d1_name_language=d1,
        d2_mention_shape=d2,
        d3_rs_integrity=d3,
        d4_topic_coherence=d4,
        d5_brand_obscurity=d5,
        total_mentions=shape["total_mentions"],
        active_dates=shape["active_dates"],
        max_daily_mentions=shape["max_daily"],
        rs_sample_brand_hit_rate=brand_hit_rate,
        rs_sample_count=len(rs_matches),
        fragrance_topic_count=topics["fragrance_topic_count"],
        already_guarded=is_guarded,
        evidence_note=evidence_note,
    )


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

def run_calibration():
    """Print calibration check for known-good and known-bad examples."""
    print("=== Calibration Check ===\n")

    # (canonical_name, brand_name, expected_action, description,
    #  total_mentions, active_dates, max_daily, brand_mention_count,
    #  rs_brand_hit_rate, n_rs_rows, n_frag_topics, n_total_topics)
    cases = [
        # Known false positives — confirmed by RES-AMB series
        # These had very few total mentions from ambiguous phrase matches
        ("Very Well",   "Berdoues",           "A", "RES-AMB3 FP — 23 false mentions",
         23,  6, 2.0,   5.0, 0.00, 8,  0, 2),
        ("So Happy",    "Flormar",            "A", "RES-AMB3 FP — 12 false mentions",
         12,  4, 2.0,   5.0, 0.00, 6,  0, 1),
        ("Too Feminine","Aigner",             "B", "RES-AMB3 FP — 8 false mentions",
          8,  3, 1.0,  10.0, 0.10, 4,  0, 1),
        ("True Icon",   "Aigner",             "B", "RES-AMB3 FP — 1 false mention",
          1,  1, 1.0,  10.0, 0.00, 1,  0, 0),
        ("I Am",        "Juicy Couture",      "A", "RES-AMB1 FP",
         45, 12, 3.0,  30.0, 0.05, 15, 0, 2),
        ("Right Now",   "West Third Brand",   "A", "RES-AMB1 FP",
         15,  5, 2.0,   2.0, 0.00, 5,  0, 1),
        ("So You",      "Alia Touch",         "B", "RES-AMB2 FP",
         55, 14, 3.0,   5.0, 0.05, 10, 1, 3),
        ("Good Vibes",  "Ricarda M.",         "B", "RES-AMB2 FP",
          8,  2, 1.0,   2.0, 0.00, 4,  0, 1),
        ("En Route",    "Botanicae Expressions","B","RES-AMB2 FP",
          2,  2, 1.0,   1.0, 0.00, 2,  0, 0),
        # RES-AMB-GLOBAL confirmed FP — "I will" / Femascu
        # Exposed Bug 1 (missing "will" in common words) and Bug 2 (D2 floor)
        # 140 mentions / 33 active dates — mature accumulation hid the false positive
        # Expected B: D1=0.85 (both tokens common), D3=1.0 (0% RS brand hit)
        ("I will",      "Femascu",            "B", "RES-AMB-GLOBAL FP — 140 mentions, 33 dates, 0% RS brand hit",
         140, 33, 13.6, 140.0, 0.00, 30, 3, 8),
        # Known-good entities — distinctive names, high volume, known brands
        ("Creed Aventus", "Creed", "D", "Iconic niche — high volume",
         3200, 90, 45.0, 3000.0, 0.90, 200, 30, 35),
        ("Maison Francis Kurkdjian Baccarat Rouge 540", "Maison Francis Kurkdjian", "D", "MFK BR540",
         2800, 85, 40.0, 2500.0, 0.92, 180, 28, 32),
        ("Dior Sauvage", "Dior", "D", "Designer flagship",
         4100, 95, 60.0, 4000.0, 0.95, 250, 35, 40),
        ("Armaf Club de Nuit Intense Man", "Armaf", "C", "Clone but real product",
          900, 60, 15.0,  800.0, 0.88, 80, 20, 25),
        ("Lattafa Khamrah", "Lattafa", "C", "Real Lattafa product",
          600, 50, 12.0,  600.0, 0.85, 60, 15, 20),
        ("Lattafa Asad", "Lattafa", "D", "Well-documented dupe",
          450, 45, 10.0,  600.0, 0.88, 50, 14, 18),
        ("Initio Oud for Greatness", "Initio", "D", "Distinctive niche name",
          800, 55, 18.0,  700.0, 0.91, 70, 22, 27),
        ("Parfums de Marly Delina Eau de Parfum", "Parfums de Marly", "D", "Has EDP token",
         1200, 65, 22.0, 1100.0, 0.92, 90, 25, 30),
        ("Diptyque L'Eau", "Diptyque", "C", "Short name but known brand",
          350, 40, 8.0,   350.0, 0.87, 45, 12, 16),
    ]

    passed = failed = 0
    for row in cases:
        (cname, bname, expected_action, desc,
         total_mentions, active_dates, max_daily, brand_mentions,
         rs_hit_rate, n_rs, n_frag_topics, n_total_topics) = row

        shape = {"total_mentions": float(total_mentions), "active_dates": active_dates,
                 "max_daily": float(max_daily)}
        topics = {"total_topics": n_total_topics, "fragrance_topic_count": n_frag_topics,
                  "has_review_topic": n_frag_topics > 5}

        # Simulate RS rows with given hit rate
        n_hits = int(n_rs * rs_hit_rate)
        rs_by_name: Dict = {
            cname: ([bname] * n_hits + ["generic text"] * (n_rs - n_hits))
        }
        brand_mention_counts: Dict = {bname: brand_mentions}

        result = score_entity(
            {"entity_id": "x", "canonical_name": cname, "brand_name": bname},
            {"x": shape},
            {"x": topics},
            rs_by_name,
            brand_mention_counts,
            _build_guarded_set(),
        )

        # Two classes:
        #   FP entities (expected A/B): FAIL if model is too lenient (C or D)
        #   Good entities (expected C/D): FAIL if model over-flags (A or B)
        is_fp = expected_action in ("A", "B")
        if is_fp:
            ok = result.action in ("A", "B")   # flagged (conservative is fine)
        else:
            ok = result.action in ("C", "D")   # clean (D when expected C is fine)
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1

        print(f"  {status}  {cname!r:50s}  risk={result.composite_risk:.3f}  "
              f"action={result.action} (expected<={expected_action})  — {desc}")

    print(f"\nCalibration: {passed} PASS / {failed} FAIL out of {len(cases)} cases")
    return failed == 0


# ---------------------------------------------------------------------------
# Production run
# ---------------------------------------------------------------------------

def run_audit(scope: str, db_url: str, min_risk: float = 0.0) -> List[EntityRiskResult]:
    import psycopg2

    print(f"Connecting to production DB ...", file=sys.stderr)
    conn = psycopg2.connect(db_url, connect_timeout=20)
    cur = conn.cursor()

    print(f"Loading entity universe (scope={scope}) ...", file=sys.stderr)
    entities = _fetch_entity_universe(cur, scope)
    print(f"  → {len(entities)} entities", file=sys.stderr)

    if not entities:
        print("No entities found for scope.", file=sys.stderr)
        conn.close()
        return []

    entity_ids = [e["entity_id"] for e in entities]

    # Batch size to avoid too-long IN clauses (SQLite: 999 limit; Postgres: fine)
    # For Postgres we can do all at once
    print("Loading mention shapes ...", file=sys.stderr)
    mention_shapes = _fetch_mention_shapes(cur, entity_ids)

    print("Loading topic stats ...", file=sys.stderr)
    topic_stats = _fetch_topic_stats(cur, entity_ids)

    print("Loading RS integrity data (bulk over resolved_signals) ...", file=sys.stderr)
    entity_cnames = [e["canonical_name"] for e in entities]
    rs_by_name = _fetch_rs_integrity(cur, entity_cnames)
    print(f"  → {sum(len(v) for v in rs_by_name.values())} RS match rows indexed", file=sys.stderr)

    print("Loading brand mention counts ...", file=sys.stderr)
    brand_mention_counts = _fetch_brand_mention_counts(cur, [])

    guarded_set = _build_guarded_set()

    conn.close()

    print("Scoring entities ...", file=sys.stderr)
    results: List[EntityRiskResult] = []
    for entity in entities:
        r = score_entity(
            entity, mention_shapes, topic_stats,
            rs_by_name, brand_mention_counts, guarded_set
        )
        if r.composite_risk >= min_risk:
            results.append(r)

    results.sort(key=lambda r: r.composite_risk, reverse=True)
    return results


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def print_report(results: List[EntityRiskResult], scope: str, min_risk: float):
    total = len(results)
    action_counts = {"A": 0, "B": 0, "C": 0, "D": 0}
    for r in results:
        action_counts[r.action] += 1

    print(f"\n{'='*78}")
    print(f"  RES-AMB-GLOBAL — Ambiguous Entity Risk Audit")
    print(f"  Scope: {scope}  |  Min risk: {min_risk:.2f}  |  Entities: {total}")
    print(f"  A={action_counts['A']}  B={action_counts['B']}  "
          f"C={action_counts['C']}  D={action_counts['D']}")
    print(f"{'='*78}")

    last_action = None
    for r in results:
        if r.action != last_action:
            labels = {
                "A": "  [A] INVESTIGATE IMMEDIATELY — likely false positive",
                "B": "  [B] ADD TO GUARD — ambiguous phrase guard recommended",
                "C": "  [C] MONITOR — watch on next pipeline run",
                "D": "  [D] LIKELY CLEAN",
            }
            print(f"\n{labels[r.action]}")
            print(f"  {'risk':>5}  {'D1':>5}  {'D2':>5}  {'D3':>5}  "
                  f"{'D4':>5}  {'D5':>5}  {'mentions':>8}  {'dates':>5}  "
                  f"{'rs_hit':>6}  guarded  name (brand)")
            last_action = r.action

        guarded_tag = "YES   " if r.already_guarded else "      "
        print(
            f"  {r.composite_risk:>5.3f}"
            f"  {r.d1_name_language:>5.2f}"
            f"  {r.d2_mention_shape:>5.2f}"
            f"  {r.d3_rs_integrity:>5.2f}"
            f"  {r.d4_topic_coherence:>5.2f}"
            f"  {r.d5_brand_obscurity:>5.2f}"
            f"  {r.total_mentions:>8.0f}"
            f"  {r.active_dates:>5d}"
            f"  {r.rs_sample_brand_hit_rate:>6.0%}"
            f"  {guarded_tag}"
            f"  {r.canonical_name!r} ({r.brand_name})"
        )
        if r.action in ("A", "B"):
            print(f"         ↳ {r.evidence_note}")

    print(f"\n{'='*78}")
    print(f"Action legend:")
    print(f"  A  risk >= 0.72  → Investigate immediately")
    print(f"  B  risk >= 0.52  → Add to _AMBIGUOUS_PHRASE_GUARD or _BLOCKED_*")
    print(f"  C  risk >= 0.32  → Monitor")
    print(f"  D  risk <  0.32  → Likely clean")
    print(f"\nDimensions: D1=name_language D2=mention_shape D3=rs_integrity "
          f"D4=topic_coherence D5=brand_obscurity")


def write_json(results: List[EntityRiskResult], path: str):
    data = [asdict(r) for r in results]
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"JSON written → {path}")


def write_csv(results: List[EntityRiskResult], path: str):
    if not results:
        return
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(results[0]).keys()))
        writer.writeheader()
        for r in results:
            writer.writerow(asdict(r))
    print(f"CSV written → {path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="RES-AMB-GLOBAL — Ambiguous Entity Risk Audit"
    )
    parser.add_argument(
        "--scope",
        choices=["active-today", "recent-movers", "tracked-market"],
        default="active-today",
    )
    parser.add_argument("--min-risk", type=float, default=0.0,
                        help="Only show entities with composite risk >= this (default: 0.0)")
    parser.add_argument("--output", help="Write JSON report to this path")
    parser.add_argument("--csv", dest="csv_path", help="Write CSV report to this path")
    parser.add_argument("--calibrate", action="store_true",
                        help="Run calibration check only (no DB required)")
    args = parser.parse_args()

    if args.calibrate:
        ok = run_calibration()
        sys.exit(0 if ok else 1)

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL environment variable required for production audit.", file=sys.stderr)
        sys.exit(1)

    results = run_audit(args.scope, db_url, args.min_risk)
    print_report(results, args.scope, args.min_risk)

    if args.output:
        write_json(results, args.output)
    if args.csv_path:
        write_csv(results, args.csv_path)


if __name__ == "__main__":
    main()
