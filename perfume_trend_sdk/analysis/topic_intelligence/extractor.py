"""Phase I5 — Deterministic Topic Extractor.

Extracts structured topics from perfume content (YouTube titles/descriptions,
Reddit post titles) using regex pattern matching. No AI used.

Topic types produced:
  'query'     — raw search query used to discover the content (YouTube only)
  'subreddit' — Reddit community where the post appeared
  'topic'     — matched semantic label from TOPIC_RULES vocabulary

All matching is case-insensitive. A single content item can match multiple
topics. Topic texts are lowercased and stripped before storage.
"""
from __future__ import annotations

import json
import re
from typing import List, NamedTuple, Optional


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------

class ExtractedTopic(NamedTuple):
    topic_type: str   # 'query' | 'subreddit' | 'topic'
    topic_text: str   # normalised text
    confidence: float  # 1.0 for deterministic matches


# ---------------------------------------------------------------------------
# Vocabulary — (compiled_regex, topic_label)
# ---------------------------------------------------------------------------

# Each tuple: (pattern_string, canonical_topic_label)
# Labels are normalised at build time (lower, stripped).
_RAW_RULES: list[tuple[str, str]] = [
    # Usage context
    (r"\bcompliment(s| getter)?\b",              "compliment getter"),
    (r"\boffice\b|\bwork(place)?\b|\bprofessional\b", "office scent"),
    (r"\bdate night\b|\bromantic\b",             "date night"),
    (r"\bsignature scent\b|\beveryday\b|\bdaily driver\b", "signature scent"),
    (r"\bwear(able)?\b.*\bgym\b|\bgym\b.*\bwear\b", "gym / sport"),
    (r"\bbeach\b|\bpooside\b|\bvacation\b|\btropic\b", "beach / vacation"),
    # Discovery context
    (r"\bblind buy\b",                           "blind buy"),
    (r"\bgift\b|\bpresent\b",                    "gift idea"),
    (r"\bsample\b|\bdecant\b",                   "sample / decant"),
    (r"\breview\b|\bfirst impression\b|\bhonest\b", "review"),
    (r"\btop\s*\d+\b|\bbest of\b|\branking\b|\bbest\s+\w+\s+fragrance\b", "ranking / best of"),
    (r"\bcompar\w+\b|\bvs\.?\b|\bversus\b",     "comparison"),
    (r"\bdupe\b|\bclone\b|\balternative\b|\blooks like\b|\bsmells like\b", "dupe / alternative"),
    # Trend signals
    (r"\btrend(ing)?\b|\bviral\b|\bhype\b",     "trending / viral"),
    (r"\bnew\s+(release|launch|arrival)\b|\bjust (launched|released|dropped)\b", "new release"),
    (r"\bflanker\b",                             "flanker"),
    (r"\breformulat\w+\b|\bvintage\b|\bold formula\b", "reformulation"),
    # Scent character
    (r"\bvanilla\b",                             "vanilla"),
    (r"\boud\b",                                 "oud"),
    (r"\bfresh\b|\bcitrus\b|\baquatic\b",        "fresh / citrus"),
    (r"\bfloral\b|\bflower\b|\brose\b|\bjasmine\b", "floral"),
    (r"\bwoody\b|\bwood\b|\bsandalwood\b|\bcedar(wood)?\b", "woody"),
    (r"\bmusky\b|\bmusk\b",                      "musk"),
    (r"\bsweet\b|\bcand(y|ied)\b|\bgourmand\b",  "sweet / gourmand"),
    (r"\bspic(y|ed)\b|\bpepper\b|\bcardamom\b",  "spicy"),
    (r"\bsmok(y|e)\b|\bleather\b",               "smoky / leather"),
    (r"\bgreen\b|\bearthy\b|\bvetiver\b|\bpatchouli\b", "green / earthy"),
    # Market category
    (r"\bniche\b",                               "niche fragrance"),
    (r"\bdesigner\b",                            "designer fragrance"),
    (r"\baffordable\b|\bbudget\b|\bcheap\b|\bvalue\b", "affordable"),
    (r"\bluxury\b|\bpremium\b|\bprestige\b",     "luxury"),
    # Gender/audience
    (r"\bmen'?s?\b|\bmasculin\w*\b|\bfor (him|men)\b", "men's fragrance"),
    (r"\bwomen'?s?\b|\bfeminin\w*\b|\bfor (her|women)\b", "women's fragrance"),
    (r"\bunisex\b|\bgender.?neutral\b",          "unisex"),
    # Performance
    (r"\blong.?last(ing)?\b|\blongevity\b|\bprojection\b|\bsillage\b", "longevity / projection"),
    # Season
    (r"\bsummer\b",                              "summer"),
    (r"\bwinter\b|\bcold weather\b|\bcozy\b",    "winter"),
    (r"\bfall\b|\bautumn\b",                     "fall / autumn"),
    (r"\bspring\b",                              "spring"),
    # Geographic / cultural
    (r"\barab\w*\b|\barabian\b|\bmiddle east\b|\borient\w*\b", "arab / oriental"),
    (r"\bfrench\b|\bparisian\b|\bparis\b",       "french fragrance"),
    (r"\bitalian\b|\bitaliano\b",               "italian fragrance"),
]

# Pre-compile all patterns
TOPIC_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(pat, re.IGNORECASE), label)
    for pat, label in _RAW_RULES
]


# ---------------------------------------------------------------------------
# Core extraction function
# ---------------------------------------------------------------------------

def extract_topics(
    *,
    title: Optional[str] = None,
    text_content: Optional[str] = None,
    query: Optional[str] = None,
    media_metadata_json: Optional[str] = None,
    source_platform: Optional[str] = None,
) -> List[ExtractedTopic]:
    """Extract all topics from a single content item.

    Returns a deduplicated list of ExtractedTopic named-tuples.
    """
    results: dict[tuple[str, str], ExtractedTopic] = {}

    def _add(ttype: str, ttext: str, conf: float = 1.0) -> None:
        ttext = ttext.strip().lower()
        if ttext and len(ttext) >= 2:
            key = (ttype, ttext)
            if key not in results:
                results[key] = ExtractedTopic(topic_type=ttype, topic_text=ttext, confidence=conf)

    # ── 1. Query (YouTube search query that surfaced this video) ────────────
    if query and query.strip():
        _add("query", query.strip())

    # ── 2. Subreddit (Reddit community) ─────────────────────────────────────
    if media_metadata_json:
        try:
            mm = json.loads(media_metadata_json) if isinstance(media_metadata_json, str) else media_metadata_json
            sub = mm.get("subreddit")
            if sub:
                _add("subreddit", sub)
        except (json.JSONDecodeError, AttributeError):
            pass

    # ── 3. Topic patterns from title + text ─────────────────────────────────
    combined_text = " ".join(filter(None, [title, text_content]))
    if combined_text.strip():
        for pattern, label in TOPIC_RULES:
            if pattern.search(combined_text):
                _add("topic", label)

    return list(results.values())
