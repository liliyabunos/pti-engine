from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

# Curated vocabulary of common perfume notes.
# Sorted longest-first so multi-word notes are matched before their components.
KNOWN_NOTES: List[str] = sorted(
    [
        # Florals
        "lily of the valley",
        "ylang ylang",
        "rose",
        "jasmine",
        "iris",
        "violet",
        "peony",
        "lily",
        "magnolia",
        "tuberose",
        "gardenia",
        "freesia",
        "carnation",
        "heliotrope",
        "neroli",
        "orris",
        # Orientals / Resins
        "oud",
        "amber",
        "benzoin",
        "labdanum",
        "cistus",
        "ambergris",
        "frankincense",
        "myrrh",
        "incense",
        "tonka",
        "vanilla",
        "caramel",
        "honey",
        # Woods / Musks
        "sandalwood",
        "cedar",
        "cedarwood",
        "vetiver",
        "patchouli",
        "musk",
        "leather",
        "oakmoss",
        "tobacco",
        "wood",
        # Citrus
        "bergamot",
        "lemon",
        "orange",
        "grapefruit",
        "lime",
        "mandarin",
        "tangerine",
        # Spices
        "cardamom",
        "pepper",
        "ginger",
        "nutmeg",
        "cinnamon",
        "clove",
        "saffron",
        # Fruits
        "raspberry",
        "blackcurrant",
        "peach",
        "apple",
        "strawberry",
        "lychee",
        "plum",
        # Aromatics
        "lavender",
        "rosemary",
        "thyme",
        "mint",
        "basil",
        # Aquatic / Ozonic
        "aquatic",
        "marine",
        "sea salt",
        # Food / Sweet
        "coffee",
        "chocolate",
        "almond",
        # Other
        "moss",
        "fern",
        "hay",
    ],
    key=len,
    reverse=True,  # longest first → multi-word notes matched first
)

_BASE_CONFIDENCE = 0.7
_OFFICIAL_CONFIDENCE = 0.9


class NoteExtractor:
    """Rule-based note mention extractor.

    Scans raw text for known perfume note names.
    If the note is listed in official_notes (from Fragrantica enrichment),
    its confidence is boosted from 0.7 to 0.9.

    Constraints:
    - No analytics
    - No connector calls
    - Deterministic output
    """

    def __init__(self, official_notes: Optional[Set[str]] = None) -> None:
        """
        Args:
            official_notes: Flat set of lowercased note names considered
                            "official" (sourced from Fragrantica enrichment).
                            Matching notes receive a higher confidence score.
        """
        self._official: Set[str] = {n.lower() for n in (official_notes or set())}

    def extract(self, text: str) -> List[Dict[str, Any]]:
        """Extract note mentions from text.

        Returns:
            List of dicts, one per unique matched note:
              - note: str (lowercased canonical)
              - confidence: float (0.7 base, 0.9 if official)
              - official_note_bonus: int (1 if official, else 0)
        """
        if not text:
            return []

        text_lower = text.lower()
        seen: Set[str] = set()
        results: List[Dict[str, Any]] = []

        for note in KNOWN_NOTES:
            if note in seen:
                continue
            if note in text_lower:
                is_official = note in self._official
                seen.add(note)
                results.append(
                    {
                        "note": note,
                        "confidence": _OFFICIAL_CONFIDENCE if is_official else _BASE_CONFIDENCE,
                        "official_note_bonus": 1 if is_official else 0,
                    }
                )

        return results

    @classmethod
    def from_enrichment_registry(
        cls, enrichment_registry: Dict[str, Any]
    ) -> "NoteExtractor":
        """Build extractor with official_notes pooled from all enriched records.

        Args:
            enrichment_registry: Dict mapping canonical_name → enriched perfume dict.
                                 Each dict may have {"official_notes": {"top", "middle", "base"}}.
        """
        note_set: Set[str] = set()
        for enrichment in enrichment_registry.values():
            official = enrichment.get("official_notes") or {}
            for tier in ("top", "middle", "base"):
                for note in official.get(tier, []):
                    note_set.add(note.lower())
        return cls(official_notes=note_set)
