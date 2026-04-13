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

        # Bare stripped base ("ambre sultan", "baccarat rouge 540") is only added
        # when it is ≥ 2 tokens — single-word stripped bases ("love", "scent",
        # "dark", "musk") are too generic and produce false matches in social text.
        if len(base_tokens) >= 2:
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
