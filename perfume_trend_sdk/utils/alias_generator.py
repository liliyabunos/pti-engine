from __future__ import annotations

import re
import unicodedata
from typing import Iterable


COMMON_BRAND_ABBREVIATIONS: dict[str, list[str]] = {
    "parfums de marly": ["pdm"],
    "maison francis kurkdjian": ["mfk"],
    "yvessaintlaurent": ["ysl"],
    "yves saint laurent": ["ysl"],
    "maison margiela": ["mm"],
}

# Single-token stripped bases that are too generic to use as standalone aliases.
# These words appear as perfume names but are common English/French words that
# would produce too many false positives if matched alone in social text.
_GENERIC_SINGLE_TOKEN_BASES: frozenset[str] = frozenset({
    # emotions / descriptors
    "love", "dark", "light", "pure", "clean", "fresh", "warm", "cool",
    "wild", "free", "brave", "rush", "sport", "dream", "bloom", "glow",
    "icon", "luxe", "spark", "gold", "jade", "silk", "velvet", "intense",
    "original", "classic", "summer", "winter", "spring", "night", "day",
    # fragrance / product generic
    "musk", "scent", "essence", "wood", "woods", "amber", "iris", "oud",
    "cedar", "moss", "fig", "tea", "rose", "noir", "bleu", "rouge",
    # colors (too short / too common)
    "red", "white", "black", "blue", "green", "or",
    # French generic terms
    "eau", "pour", "homme", "femme", "nuit", "soleil",
})

# Concentration and product-form terms that appear as trailing suffixes in
# perfume names from the fragrance_master seed data.  Ordered longest-first so
# multi-word suffixes are stripped before shorter ones.
_CONCENTRATION_SUFFIXES: tuple[str, ...] = (
    "extrait de parfum",
    "eau de parfum",
    "eau de toilette",
    "body spray",
    "body mist",
    "extrait",
    "parfum",
    "edp",
    "edt",
)


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).lower().strip()
    # Strip possessives before removing punctuation so "amouage's" → "amouage"
    # and "d'hermes" → "d hermes" (apostrophe becomes space, keeps both parts)
    text = re.sub(r"'s\b", "", text)     # amouage's → amouage
    text = re.sub(r"'", " ", text)       # d'hermes → d hermes (preserves d hermes)
    text = re.sub(r"[^\w\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def strip_concentration(perfume_name: str) -> str:
    """
    Return the base perfume name with trailing concentration / product-form
    term removed.

    Handles two common patterns in fragrance_master seed data:
      • "Ambre Sultan Eau de Parfum"       → "Ambre Sultan"
      • "Philosykos - Eau de Parfum"       → "Philosykos"
      • "Sauvage Elixir"                   → "Sauvage Elixir"  (unchanged)

    Input is the RAW (un-normalised) perfume_name from the CSV.
    Returns the stripped version, also un-normalised (preserving original casing).
    The caller normalises the result with normalize_text() as needed.
    """
    name = perfume_name.strip()

    # Handle "Name - Concentration" dash notation first
    dash_match = re.match(
        r"^(.+?)\s*-\s*(?:" + "|".join(re.escape(s) for s in _CONCENTRATION_SUFFIXES) + r")\s*$",
        name,
        re.IGNORECASE,
    )
    if dash_match:
        return dash_match.group(1).strip()

    # Handle plain trailing suffix: "Ambre Sultan Eau de Parfum"
    name_lower = name.lower()
    for suffix in _CONCENTRATION_SUFFIXES:          # already longest-first
        if name_lower.endswith(" " + suffix):
            return name[: -(len(suffix) + 1)].strip()
        if name_lower == suffix:                    # the name IS only a suffix word
            return name                             # don't strip — nothing left

    return name


def compact_text(value: str) -> str:
    """Used for cases like YSL / YvesSaintLaurent normalization lookup."""
    return re.sub(r"\s+", "", normalize_text(value))


def generate_brand_aliases(brand_name: str) -> list[str]:
    normalized_brand = normalize_text(brand_name)
    aliases = {normalized_brand}

    compact_brand = compact_text(brand_name)
    if compact_brand in COMMON_BRAND_ABBREVIATIONS:
        aliases.update(COMMON_BRAND_ABBREVIATIONS[compact_brand])

    if normalized_brand in COMMON_BRAND_ABBREVIATIONS:
        aliases.update(COMMON_BRAND_ABBREVIATIONS[normalized_brand])

    return sorted(a for a in aliases if a)


def generate_perfume_aliases(brand_name: str, perfume_name: str) -> list[str]:
    """
    Generate alias strings for a single perfume entity.

    Phase 1 rules (existing):
      - canonical short perfume name
      - brand + perfume
      - perfume + 'perfume'
      - known brand abbreviation + perfume

    Phase 2 rules (concentration stripping):
      When the perfume name contains a trailing concentration term
      (e.g. "Ambre Sultan Eau de Parfum"), also generate aliases from the
      stripped base name ("Ambre Sultan"):
        - stripped base alone
        - brand + stripped base
        - stripped base + 'perfume'
        - known brand abbreviation + stripped base

    All aliases are returned normalised (lowercase, punctuation-stripped).
    """
    brand = normalize_text(brand_name)
    perfume = normalize_text(perfume_name)

    if not perfume:
        return []

    aliases: set[str] = {
        perfume,
        f"{brand} {perfume}".strip(),
        f"{perfume} perfume".strip(),
    }

    for brand_alias in generate_brand_aliases(brand_name):
        if brand_alias != brand:
            aliases.add(f"{brand_alias} {perfume}".strip())

    # --- Phase 2: concentration-stripped short aliases ---
    base_raw = strip_concentration(perfume_name)
    base = normalize_text(base_raw)
    base_tokens = base.split()

    # Only process if the stripped base is genuinely different from the full name
    # and non-trivial in length.
    if base and base != perfume and len(base) > 1:
        # Brand-prefixed forms are always specific enough to add safely.
        # e.g. "by kilian love" is unambiguous even though "love" alone is not.
        aliases.add(f"{brand} {base}".strip())
        for brand_alias in generate_brand_aliases(brand_name):
            if brand_alias != brand:
                aliases.add(f"{brand_alias} {base}".strip())

        # Bare stripped base ("ambre sultan", "baccarat rouge 540") is always
        # added as a standalone alias UNLESS it is a single generic word.
        # Multi-token bases (≥2 tokens) are always specific enough.
        # Single-token bases ("aventus", "sauvage") are added when they are
        # not in the generic blocklist — these are unambiguous perfume names.
        if len(base_tokens) >= 2 or (
            len(base_tokens) == 1 and base not in _GENERIC_SINGLE_TOKEN_BASES
        ):
            aliases.add(base)
            aliases.add(f"{base} perfume".strip())

    return sorted(a for a in aliases if a)


def dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
