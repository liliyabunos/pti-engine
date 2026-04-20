from __future__ import annotations

"""Note canonicalization — groups semantic variants into single canonical entities.

Rules:
  1. Each note in the `notes` table is mapped to exactly one canonical note.
  2. Self-mapping is the default: most notes ARE their own canonical.
  3. Explicit MERGE_GROUPS define semantic variants that share a canonical root.
  4. Canonical name is always the shortest / most common form.
  5. note_family is a broad olfactive classification for analytics grouping.

This module is purely definitional — no DB I/O.
"""

from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Merge group definitions
# ---------------------------------------------------------------------------
# Format: { "canonical_normalized_name": ["variant1", "variant2", ...] }
# All names are normalized (lowercase, stripped).
# The canonical itself should appear first in each list.
# ---------------------------------------------------------------------------

MERGE_GROUPS: Dict[str, List[str]] = {
    # Citruses
    "bergamot": ["bergamot", "calabrian bergamot"],
    "lemon": ["lemon", "sicilian lemon"],
    "orange": ["orange", "sicilian orange", "blood orange"],
    "mandarin": ["mandarin orange", "green mandarin", "italian mandarin", "sicilian mandarin"],
    "grapefruit": ["grapefruit"],

    # Fruits
    "blackcurrant": ["blackcurrant", "black currant", "blackcurrant syrup"],
    "lychee": ["lychee", "litchi"],

    # Floral
    "rose": ["rose", "damask rose", "turkish rose"],
    "jasmine": ["jasmine", "egyptian jasmine", "water jasmine"],

    # Woody / resins
    "cedar": ["cedar", "cedarwood", "atlas cedar", "virginian cedar"],
    "patchouli": ["patchouli", "patchouli leaf"],
    "benzoin": ["benzoin", "siam benzoin"],
    "labdanum": ["labdanum", "spanish labdanum"],
    "tobacco": ["tobacco", "tobacco leaf"],

    # Musks / amber
    "musk": ["musk", "white musk"],
    "amber": ["amber", "ambermax™"],
    "vanilla": ["vanilla", "vanilla absolute", "madagascar vanilla"],

    # Spices
    "pepper": ["pepper", "black pepper", "pink pepper", "sichuan pepper"],
}

# Reverse lookup: normalized_variant → canonical_normalized_name
_VARIANT_TO_CANONICAL: Dict[str, str] = {}
for canonical, variants in MERGE_GROUPS.items():
    for v in variants:
        _VARIANT_TO_CANONICAL[v] = canonical

# ---------------------------------------------------------------------------
# Note families for broad classification
# ---------------------------------------------------------------------------

NOTE_FAMILIES: Dict[str, str] = {
    # Citrus
    "bergamot": "citrus",
    "lemon": "citrus",
    "orange": "citrus",
    "mandarin": "citrus",
    "grapefruit": "citrus",
    "lime": "citrus",
    "yuzu": "citrus",
    "citruses": "citrus",

    # Floral
    "rose": "floral",
    "jasmine": "floral",
    "peony": "floral",
    "iris": "floral",
    "violet": "floral",
    "tuberose": "floral",
    "gardenia": "floral",
    "magnolia": "floral",
    "frangipani": "floral",
    "lilac": "floral",
    "lotus": "floral",
    "osmanthus": "floral",
    "heliotrope": "floral",
    "neroli": "floral",
    "freesia": "floral",
    "honeysuckle": "floral",

    # Fruity
    "blackcurrant": "fruity",
    "lychee": "fruity",
    "peach": "fruity",
    "raspberry": "fruity",
    "pear": "fruity",
    "apple": "fruity",
    "pineapple": "fruity",
    "apricot": "fruity",
    "pomegranate": "fruity",
    "red berries": "fruity",
    "fruits": "fruity",
    "fruity notes": "fruity",

    # Woody
    "cedar": "woody",
    "sandalwood": "woody",
    "patchouli": "woody",
    "vetiver": "woody",
    "agarwood": "woody",
    "guaiac wood": "woody",
    "birch": "woody",
    "mahogany": "woody",
    "oud": "woody",
    "woodsy notes": "woody",
    "atlas cedar": "woody",
    "virginian cedar": "woody",

    # Musky / powdery
    "musk": "musky",
    "amber": "musky",
    "ambergris": "musky",
    "ambroxan": "musky",
    "cashmeran": "musky",
    "iso e super": "musky",
    "white suede": "musky",

    # Sweet / gourmand
    "vanilla": "sweet",
    "tonka bean": "sweet",
    "caramel": "sweet",
    "praline": "sweet",
    "sugar": "sweet",
    "benzoin": "sweet",
    "coumarin": "sweet",
    "brown sugar": "sweet",
    "rum": "sweet",
    "dates": "sweet",
    "almond": "sweet",
    "bitter almond": "sweet",

    # Spicy
    "pepper": "spicy",
    "cardamom": "spicy",
    "cinnamon": "spicy",
    "saffron": "spicy",
    "ginger": "spicy",
    "cumin": "spicy",
    "clary sage": "spicy",
    "nutmeg": "spicy",

    # Resinous / smoky
    "labdanum": "resinous",
    "tobacco": "resinous",
    "incense": "resinous",
    "myrrh": "resinous",
    "styrax": "resinous",
    "elemi": "resinous",
    "fir resin": "resinous",
    "oakmoss": "resinous",
    "leather": "resinous",

    # Fresh / aquatic
    "green notes": "fresh",
    "herbal notes": "fresh",
    "water notes": "fresh",
    "mint": "fresh",
    "lavender": "fresh",
    "geranium": "fresh",
    "spicy notes": "spicy",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize_note_name(name: str) -> str:
    """Lowercase + strip a note name for matching."""
    return name.lower().strip()


def get_canonical_normalized(normalized_name: str) -> str:
    """Return the canonical normalized name for a given note normalized_name.

    If no merge group applies, the note is its own canonical.
    """
    return _VARIANT_TO_CANONICAL.get(normalized_name, normalized_name)


def get_note_family(canonical_normalized: str) -> Optional[str]:
    """Return the olfactive family for a canonical note, or None."""
    return NOTE_FAMILIES.get(canonical_normalized)


def all_canonical_names() -> List[str]:
    """Return the sorted list of all distinct canonical normalized names.

    Includes both merge-group canonicals and self-canonical notes.
    This function is informational — the actual canonical list comes from DB.
    """
    return sorted(set(_VARIANT_TO_CANONICAL.values()))


def build_canonical_entries(all_notes: List[Tuple[str, str, str]]) -> List[Dict]:
    """Build the canonical entry list from all notes in the DB.

    Args:
        all_notes: list of (note_id, name, normalized_name) from notes table.

    Returns:
        List of dicts: {canonical_name, normalized_name, note_family}
        Deduplicated — one entry per distinct canonical_normalized_name.
    """
    seen: set[str] = set()
    entries: List[Dict] = []

    for note_id, name, normalized_name in all_notes:
        canonical_norm = get_canonical_normalized(normalized_name)

        if canonical_norm in seen:
            continue
        seen.add(canonical_norm)

        # Use the original note's name if it's the canonical, else title-case the canonical
        if canonical_norm == normalized_name:
            display_name = name  # preserve original casing from DB
        else:
            display_name = canonical_norm.title()

        entries.append({
            "canonical_name": display_name,
            "normalized_name": canonical_norm,
            "note_family": get_note_family(canonical_norm),
        })

    return entries


def build_note_mapping(all_notes: List[Tuple[str, str, str]]) -> Dict[str, str]:
    """Build note_id → canonical_normalized_name mapping.

    Args:
        all_notes: list of (note_id, name, normalized_name)

    Returns:
        Dict mapping note_id → canonical_normalized_name
    """
    return {
        note_id: get_canonical_normalized(normalized_name)
        for note_id, name, normalized_name in all_notes
    }
