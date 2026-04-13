from __future__ import annotations

import re
from typing import Any, Dict, List


# Thresholds (configurable)
MIN_MENTION_COUNT = 2
MIN_DISTINCT_SOURCES = 2

# Rejection: too short
MIN_TOKEN_LENGTH = 4

# Generic words that are not entity candidates on their own
GENERIC_WORDS = {
    "perfume", "perfumes", "fragrance", "fragrances",
    "cologne", "colognes", "scent", "scents",
    "best", "top", "new", "review", "haul",
    "cheap", "luxury", "niche", "viral", "trending",
    "smell", "smells", "smelling", "wear", "wearing",
    "recommend", "recommendation", "try", "tried",
    "like", "love", "hate", "worth", "beautiful",
    "amazing", "incredible", "underrated", "clone",
    "dupe", "similar", "inspired",
}

# Spam / noise patterns
SPAM_PATTERNS = [
    r"^\d+$",                    # pure digits
    r"^[\W_]+$",                 # only punctuation/symbols
    r"\btop\s+\d+\b",            # "top 10", "top 5"
    r"\bbest\s+\d+\b",           # "best 5"
    r"\d+\s*(ml|oz|g)\b",        # "100ml", "3.4oz"
    r"https?://",                # URLs
    r"#\w+",                     # hashtags
    r"@\w+",                     # mentions
]

_SPAM_RE = [re.compile(p, re.IGNORECASE) for p in SPAM_PATTERNS]


def _is_spam(text: str) -> bool:
    for pattern in _SPAM_RE:
        if pattern.search(text):
            return True
    return False


def _is_too_short(text: str) -> bool:
    tokens = text.split()
    return all(len(t) <= MIN_TOKEN_LENGTH for t in tokens)


def _is_all_generic(text: str) -> bool:
    tokens = text.lower().split()
    return all(t in GENERIC_WORDS for t in tokens)


def is_valid_candidate(candidate: Dict[str, Any]) -> bool:
    text = candidate.get("text", "").strip()
    if not text:
        return False
    if _is_spam(text):
        return False
    if _is_too_short(text):
        return False
    if _is_all_generic(text):
        return False
    return True


def meets_promotion_threshold(candidate: Dict[str, Any]) -> bool:
    count = candidate.get("count", 0)
    sources = candidate.get("sources", 0)
    return count >= MIN_MENTION_COUNT or sources >= MIN_DISTINCT_SOURCES


def filter_candidates(
    candidates: List[Dict[str, Any]],
    min_count: int = MIN_MENTION_COUNT,
) -> List[Dict[str, Any]]:
    filtered = []

    for c in candidates:
        text = c["text"]

        if len(text) <= 3:
            continue

        if c["count"] < min_count and c["sources"] < MIN_DISTINCT_SOURCES:
            continue

        if not is_valid_candidate(c):
            continue

        filtered.append(c)

    return filtered
