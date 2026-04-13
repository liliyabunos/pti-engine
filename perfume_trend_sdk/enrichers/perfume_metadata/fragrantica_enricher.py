from __future__ import annotations

from typing import Dict, List, Optional


# Fields that must NEVER be overwritten by enrichment
_PROTECTED_FIELDS = {
    "canonical_name",
    "brand_id",
    "perfume_id",
    "fragrance_id",
    "normalized_name",
}

# Fields to add from fragrantica record (additive only)
_ENRICHMENT_FIELDS: List[str] = [
    "accords",
    "notes_top",
    "notes_middle",
    "notes_base",
    "rating_value",
    "rating_count",
    "perfumer",
    "gender",
    "similar_perfumes",
]


class FragranticaEnricher:
    """Add Fragrantica metadata to a canonical perfume record.

    Rules:
    - NEVER overwrites protected fields (canonical_name, brand_id, etc.)
    - Additive only — only adds fields if they have a meaningful value
    - Missing fragrantica fields are skipped (no None values added)
    - Returns enriched copy; original record is not mutated
    """

    @staticmethod
    def _get(record: object, field: str) -> object:
        """Get a field from either a dict or a Pydantic model."""
        if isinstance(record, dict):
            return record.get(field)
        return getattr(record, field, None)

    def enrich(self, perfume_record: Dict, fragrantica_record: object) -> Dict:
        """Enrich a perfume record with data from a normalized Fragrantica record.

        Args:
            perfume_record: Canonical perfume dict (may have any structure).
            fragrantica_record: Normalized Fragrantica dict from FragranticaNormalizer.

        Returns:
            New dict = copy of perfume_record + non-None fragrantica fields.
        """
        enriched = dict(perfume_record)

        for field in _ENRICHMENT_FIELDS:
            if field in _PROTECTED_FIELDS:
                # Safety guard — should never trigger with current lists
                continue

            value = self._get(fragrantica_record, field)

            # Skip None values
            if value is None:
                continue

            # Skip empty lists
            if isinstance(value, list) and len(value) == 0:
                continue

            enriched[field] = value

        # Attach structured official_notes (top / middle / base)
        notes_top = self._get(fragrantica_record, "notes_top") or []
        notes_middle = self._get(fragrantica_record, "notes_middle") or []
        notes_base = self._get(fragrantica_record, "notes_base") or []
        if notes_top or notes_middle or notes_base:
            enriched["official_notes"] = {
                "top": list(notes_top),
                "middle": list(notes_middle),
                "base": list(notes_base),
            }

        # Attach enrichment provenance
        source_url = self._get(fragrantica_record, "source_url")
        if source_url:
            enriched["fragrantica_source_url"] = source_url

        raw_payload_ref = self._get(fragrantica_record, "raw_payload_ref")
        if raw_payload_ref:
            enriched["fragrantica_raw_payload_ref"] = raw_payload_ref

        normalized_at = self._get(fragrantica_record, "normalized_at")
        if normalized_at:
            enriched["fragrantica_enriched_at"] = normalized_at

        return enriched
