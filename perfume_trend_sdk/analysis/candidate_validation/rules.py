from __future__ import annotations

"""Rule assets for Phase 3B candidate validation.

This module contains pure-Python data structures and helper functions used by
the classifier.  No database access here — all DB-loaded data is passed in as
arguments so the classifier stays stateless and testable.
"""

import re
from typing import FrozenSet, Set

# ---------------------------------------------------------------------------
# Stopwords — common English function words
# ---------------------------------------------------------------------------

STOPWORDS: FrozenSet[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "not", "no", "nor", "so",
    "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "must", "shall",
    "can", "i", "me", "my", "we", "our", "you", "your", "he", "she",
    "it", "they", "his", "her", "its", "their",
    "this", "that", "these", "those",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "up",
    "out", "about", "into", "through", "during", "before", "after",
    "above", "below", "between",
    "if", "then", "as", "than", "when", "while", "each",
    "here", "there", "where", "what", "who", "how",
    "all", "both", "few", "more", "most", "other", "some", "such",
    "only", "own", "same", "just", "also", "get", "got",
    "very", "really", "quite", "already", "still", "yet",
    # Contracted forms that appear after punctuation stripping
    "s", "t", "re", "ll", "ve", "d", "m",
})

# ---------------------------------------------------------------------------
# Contraction suffixes — second token in "don t", "aren t", etc.
# ---------------------------------------------------------------------------

CONTRACTION_SUFFIXES: FrozenSet[str] = frozenset({"t", "s", "re", "ll", "ve", "d", "m"})

# ---------------------------------------------------------------------------
# Explicit stop-phrases — high-frequency English 2–4-gram fragments
# Known noise from Phase 3A ingestion results.
# ---------------------------------------------------------------------------

STOP_PHRASES: FrozenSet[str] = frozenset({
    # Desire / intent
    "want to", "wanted to", "trying to", "going to", "looking for",
    "wondering if", "thinking about", "need to", "need a",
    # Quantities / prepositions
    "out of", "from the", "back to", "based on", "kind of", "out there",
    "up and", "out and", "in my", "on my", "for me", "for a",
    "of a", "in a", "on a", "at a", "with a",
    # Discourse / hedging
    "all the", "any recommendations", "you want", "you re",
    "you guys", "know any", "m looking", "m not", "ll be", "ve tried",
    "ve been", "had a", "got the", "had to",
    # Pronouns + verb
    "me it", "like it", "love it", "smell like", "smells like", "scent or",
    "these are", "both on",
    # Sentence continuations
    "fragrance i", "fragrances i", "fragrances that", "fragrances and",
    "bottle of", "get a",
    # Common Reddit fragments
    "anyone else", "similar to", "might be", "years ago", "different from",
    "top note", "dry down", "them i", "notes in", "collection so",
    "stands out", "now i", "think i", "know i", "just a", "me and",
    "it s", "that i", "be a", "am a",
    "it was", "it is", "it will", "we have", "we are", "they are",
    "have been", "has been", "had been",
})

# ---------------------------------------------------------------------------
# URL / technical artifacts
# ---------------------------------------------------------------------------

URL_TOKENS: FrozenSet[str] = frozenset({
    "http", "https", "www", "bit", "com", "org", "net", "html", "php",
    "utm", "ref", "url", "link", "click", "ly",
})

# ---------------------------------------------------------------------------
# Concentration / product-form words — strong signal that a phrase contains
# a perfume name fragment (e.g. "dior sauvage eau de parfum")
# ---------------------------------------------------------------------------

CONCENTRATION_WORDS: FrozenSet[str] = frozenset({
    "eau", "parfum", "toilette", "cologne", "extrait", "edp", "edt", "edc",
})

# ---------------------------------------------------------------------------
# Note keywords — terms known to be perfume ingredient / olfactive notes.
# If a candidate consists entirely of note terms, type = note.
# If mixed with brand terms, type = perfume.
# ---------------------------------------------------------------------------

NOTE_KEYWORDS: FrozenSet[str] = frozenset({
    # Florals
    "rose", "jasmine", "iris", "violet", "peony", "magnolia", "lily",
    "orchid", "ylang", "neroli", "tuberose", "carnation", "gardenia",
    "osmanthus", "lotus", "freesia", "lavender", "geranium", "mimosa",
    "narcissus", "heliotrope", "hyacinth",
    # Citrus
    "bergamot", "lemon", "lime", "grapefruit", "mandarin", "orange",
    "yuzu", "tangerine", "citrus", "pomelo", "blood orange",
    # Woods
    "sandalwood", "cedar", "oud", "agarwood", "vetiver", "oakmoss",
    "birch", "guaiac", "cypress", "pine", "rosewood", "teakwood",
    # Musks & resins
    "musk", "amber", "ambergris", "frankincense", "myrrh", "benzoin",
    "labdanum", "cistus", "olibanum", "beeswax", "ambroxan", "cashmeran",
    # Spices
    "vanilla", "tonka", "cinnamon", "cardamom", "clove", "pepper",
    "ginger", "saffron", "nutmeg", "cumin", "coriander",
    # Earthy / gourmand
    "patchouli", "tobacco", "leather", "suede", "smoke", "incense",
    "hay", "praline", "caramel", "cocoa", "coffee", "almond", "coconut",
    "marzipan", "honey",
    # Fresh / aquatic
    "aquatic", "marine", "sea", "rain", "green", "grass", "cucumber",
    "mint", "eucalyptus", "petrichor",
    # Other recognizable note words
    "vetiver", "iso", "hedione", "ambrox", "akigalawood", "musks",
    "woods", "floral", "woody", "oriental", "gourmand", "aromatic",
    "chypre", "fougere", "aldehydic",
    # Fruit
    "apple", "pear", "peach", "plum", "blackcurrant", "raspberry",
    "strawberry", "blueberry", "apricot", "fig", "cherry",
})

# ---------------------------------------------------------------------------
# Perfume-community vocabulary — words common in fragrance discussion but
# NOT by themselves entity names (used to catch "fragrance i", "dry down" etc.)
# ---------------------------------------------------------------------------

FRAGRANCE_COMMUNITY_WORDS: FrozenSet[str] = frozenset({
    "fragrance", "fragrances", "perfume", "perfumes", "cologne", "colognes",
    "scent", "scents", "smell", "smells", "spray", "spritz", "wearable",
    "longevity", "sillage", "projection", "blind", "buy", "sample",
    "decant", "layering", "dupe", "clone", "inspired", "flanker",
    "concentration", "batch", "signature", "house", "niche", "designer",
    "mainstream", "reformulation", "vintage", "discontinued",
    "skin", "chemistry", "nose", "tester", "ml", "oz",
})

# ---------------------------------------------------------------------------
# Tokens to exclude when building brand_tokens from DB brand names.
# These are generic English or French words that appear in brand names
# but would cause too many false positive matches.
# ---------------------------------------------------------------------------

AMBIGUOUS_BRAND_TOKENS: FrozenSet[str] = frozenset({
    # Prepositions / articles (Romance languages)
    "lab", "fire", "love", "blue", "green", "black", "white", "red",
    "club", "house", "man", "men", "les", "pour", "new", "free", "art",
    "arts", "son", "sur", "set", "the", "de", "di", "le", "la", "du",
    "del", "des", "von", "van", "el", "al", "ibn", "bou", "un", "une",
    "blossom", "reflection",
    # Generic descriptor words common in multi-word brand names
    "eau", "parfums", "parfumerie", "profumo", "profumi", "perfumery",
    "fragrance", "fragrances", "atelier", "maison", "edition", "editions",
    "collection", "studio", "laboratory",
    # Common English words that appear in long/unusual brand name strings
    # and would produce massive false positives if kept as brand signals
    "perfume", "perfumes", "know", "people", "project", "april", "rose",
    "gun", "what", "gun", "has", "not", "who", "don",
    "jack", "just", "gun", "rook", "timothy", "han",
    # Numbers-as-words and ordinals
    "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "first", "second", "third",
})

# ---------------------------------------------------------------------------
# Social-handle pattern — catches YouTube / Instagram handles in descriptions
# ---------------------------------------------------------------------------

_SOCIAL_HANDLE_RE = re.compile(r"^[a-z][a-z0-9]{4,}$")  # lowercase alnum, 5+ chars, no spaces


def looks_like_social_handle(text: str) -> bool:
    """Return True if the phrase looks like a social media handle / username.

    Heuristics:
    - Single token (no spaces)
    - Lowercase alphanumeric only
    - 5–30 characters
    - No vowels in expected positions for a real word (consonant-heavy)
    """
    stripped = text.strip()
    if " " in stripped:
        return False
    if not _SOCIAL_HANDLE_RE.match(stripped):
        return False
    # Reject if it looks like a recognizable word (has vowels normally distributed)
    # Simple heuristic: consonant run of 3+ without a vowel suggests a handle
    vowels = set("aeiou")
    consonant_run = 0
    for ch in stripped:
        if ch not in vowels:
            consonant_run += 1
            if consonant_run >= 4:
                return True
        else:
            consonant_run = 0
    return False


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def stopword_ratio(tokens: list) -> float:
    """Fraction of tokens that are pure stopwords."""
    if not tokens:
        return 1.0
    return sum(1 for t in tokens if t in STOPWORDS) / len(tokens)


def content_tokens(tokens: list) -> list:
    """Return tokens that are NOT stopwords."""
    return [t for t in tokens if t not in STOPWORDS]


def is_contraction_fragment(tokens: list) -> bool:
    """Detect patterns like "don t", "aren t", "can t", "you re", "i ve"."""
    if len(tokens) == 2 and tokens[1] in CONTRACTION_SUFFIXES:
        return True
    if len(tokens) == 2 and tokens[0] in CONTRACTION_SUFFIXES:
        return True
    # "m not", "ll be" — modal contraction starts
    if len(tokens) == 2 and tokens[0] in {"m", "ll", "ve", "d", "re"}:
        return True
    return False


def is_url_artifact(tokens: list) -> bool:
    """Return True if any token is a URL / technical artifact."""
    return bool(set(tokens) & URL_TOKENS)


# ---------------------------------------------------------------------------
# DB-loaded asset builders (call once per job run, pass results to classifier)
# ---------------------------------------------------------------------------

def load_brand_tokens(session) -> Set[str]:
    """Load brand names from DB and derive a set of distinctive brand tokens.

    Strategy:
    - Take the ``name`` column from the ``brands`` table.
    - Lowercase and split each name into tokens.
    - Keep tokens that are >= 3 chars, not in STOPWORDS, not in
      AMBIGUOUS_BRAND_TOKENS.
    - Also add the full lowercased brand name (for exact-phrase matching).
    """
    from sqlalchemy import text as sa_text

    rows = session.execute(
        sa_text("SELECT name FROM brands WHERE name IS NOT NULL")
    ).fetchall()

    tokens: Set[str] = set()
    for (name,) in rows:
        name_norm = name.lower().strip()
        # Full brand name stored for reference (not used as individual token)
        # Individual tokens — apply strict filtering
        for tok in re.split(r"[\s\-\.\+\/]+", name_norm):
            tok = tok.strip("()[].,!?\"'0123456789")
            if (
                len(tok) >= 4                               # minimum 4 chars
                and tok not in STOPWORDS
                and tok not in AMBIGUOUS_BRAND_TOKENS
                and tok not in NOTE_KEYWORDS                # notes stay as notes
                and tok not in FRAGRANCE_COMMUNITY_WORDS   # generic vocab
                and tok not in CONCENTRATION_WORDS         # structural markers, not brand signals
                and not tok.isdigit()                      # no pure numbers
                and re.match(r"^[a-z]+$", tok)            # alpha only
            ):
                tokens.add(tok)

    return tokens


def load_note_names(session) -> Set[str]:
    """Load normalized note names from notes_canonical table.

    Falls back gracefully to empty set if the table has no rows or doesn't exist.
    """
    from sqlalchemy import text as sa_text

    try:
        rows = session.execute(
            sa_text(
                "SELECT normalized_name FROM notes_canonical "
                "WHERE normalized_name IS NOT NULL"
            )
        ).fetchall()
        return {r[0].lower().strip() for r in rows if r[0]}
    except Exception:
        return set()
