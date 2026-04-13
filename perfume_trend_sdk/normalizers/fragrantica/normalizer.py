from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class FragranticaPerfumeRecord(BaseModel):
    source_name: str = "fragrantica"
    source_url: str
    brand_name: Optional[str] = None
    perfume_name: Optional[str] = None
    accords: List[str] = Field(default_factory=list)
    notes_top: List[str] = Field(default_factory=list)
    notes_middle: List[str] = Field(default_factory=list)
    notes_base: List[str] = Field(default_factory=list)
    rating_value: Optional[float] = None
    rating_count: Optional[int] = None
    release_year: Optional[int] = None
    perfumer: Optional[str] = None
    gender: Optional[str] = None
    similar_perfumes: List[str] = Field(default_factory=list)
    raw_payload_ref: Optional[str] = None
    normalized_at: Optional[str] = None


class FragranticaNormalizer:
    """Normalize parsed Fragrantica data into a structured internal record.

    Rules:
    - Preserves source_url and raw_payload_ref
    - Does NOT resolve entities
    - Does NOT mutate canonical data
    - Tolerates missing fields in parsed dict
    """

    def normalize(self, parsed: Dict, raw_payload_ref: str) -> FragranticaPerfumeRecord:
        return FragranticaPerfumeRecord(
            source_url=self._safe_str(parsed.get("source_url")) or "",
            brand_name=self._safe_str(parsed.get("brand_name")),
            perfume_name=self._safe_str(parsed.get("perfume_name")),
            accords=self._safe_list(parsed.get("accords")),
            notes_top=self._safe_list(parsed.get("notes_top")),
            notes_middle=self._safe_list(parsed.get("notes_middle")),
            notes_base=self._safe_list(parsed.get("notes_base")),
            rating_value=self._safe_float(parsed.get("rating_value")),
            rating_count=self._safe_int(parsed.get("rating_count")),
            release_year=self._safe_int(parsed.get("release_year")),
            perfumer=self._safe_str(parsed.get("perfumer")),
            gender=self._safe_str(parsed.get("gender")),
            similar_perfumes=self._safe_list(parsed.get("similar_perfumes")),
            raw_payload_ref=raw_payload_ref,
            normalized_at=datetime.now(timezone.utc).isoformat(),
        )

    def _safe_str(self, value: object) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    def _safe_list(self, value: object) -> List[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _safe_float(self, value: object) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    def _safe_int(self, value: object) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None
