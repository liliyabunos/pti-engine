from __future__ import annotations

from pathlib import Path

import pytest

from perfume_trend_sdk.connectors.fragrantica.parser import FragranticaParser
from perfume_trend_sdk.enrichers.perfume_metadata.fragrantica_enricher import FragranticaEnricher
from perfume_trend_sdk.normalizers.fragrantica.normalizer import FragranticaNormalizer

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "fragrantica_perfume_page.html"
SOURCE_URL = "https://www.fragrantica.com/perfume/Parfums-de-Marly/Delina-38737.html"
RAW_PAYLOAD_REF = "data/raw/fragrantica/test_run/00001.json"


@pytest.fixture(scope="module")
def fixture_html() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parsed(fixture_html: str) -> dict:
    return FragranticaParser().parse(fixture_html, SOURCE_URL)


@pytest.fixture(scope="module")
def normalized(parsed: dict) -> dict:
    return FragranticaNormalizer().normalize(parsed, RAW_PAYLOAD_REF)


@pytest.fixture(scope="module")
def base_perfume_record() -> dict:
    """A canonical perfume record as it would come from FragranceMasterStore."""
    return {
        "fragrance_id": "pdm-delina-001",
        "canonical_name": "Parfums de Marly Delina",
        "normalized_name": "parfums de marly delina",
        "brand_name": "Parfums de Marly",
        "perfume_name": "Delina",
        "brand_id": 42,
        "perfume_id": 99,
    }


def test_enrichment_flow_with_fixture(base_perfume_record: dict, normalized: dict) -> None:
    """Full flow: parse → normalize → enrich → assert accords present."""
    enriched = FragranticaEnricher().enrich(base_perfume_record, normalized)

    assert isinstance(enriched, dict)
    assert "accords" in enriched
    assert isinstance(enriched["accords"], list)
    assert len(enriched["accords"]) > 0
    assert "floral" in enriched["accords"]


def test_enriched_record_has_notes(base_perfume_record: dict, normalized: dict) -> None:
    enriched = FragranticaEnricher().enrich(base_perfume_record, normalized)
    assert isinstance(enriched.get("notes_top"), list)
    assert isinstance(enriched.get("notes_middle"), list)
    assert isinstance(enriched.get("notes_base"), list)


def test_enriched_record_has_rating(base_perfume_record: dict, normalized: dict) -> None:
    enriched = FragranticaEnricher().enrich(base_perfume_record, normalized)
    assert isinstance(enriched.get("rating_value"), float)
    assert isinstance(enriched.get("rating_count"), int)


def test_enricher_does_not_overwrite_canonical_name(base_perfume_record: dict, normalized: dict) -> None:
    """canonical_name must remain unchanged even if Fragrantica has a different brand_name."""
    modified_fragrantica = dict(normalized)
    modified_fragrantica["brand_name"] = "SOME OTHER BRAND"

    enriched = FragranticaEnricher().enrich(base_perfume_record, modified_fragrantica)

    # canonical_name must not be touched
    assert enriched["canonical_name"] == "Parfums de Marly Delina"


def test_enricher_does_not_overwrite_brand_id(base_perfume_record: dict, normalized: dict) -> None:
    enriched = FragranticaEnricher().enrich(base_perfume_record, normalized)
    assert enriched["brand_id"] == 42


def test_enricher_does_not_overwrite_perfume_id(base_perfume_record: dict, normalized: dict) -> None:
    enriched = FragranticaEnricher().enrich(base_perfume_record, normalized)
    assert enriched["perfume_id"] == 99


def test_enricher_adds_provenance(base_perfume_record: dict, normalized: dict) -> None:
    """Enricher must attach source URL and raw payload ref for traceability."""
    enriched = FragranticaEnricher().enrich(base_perfume_record, normalized)
    assert enriched.get("fragrantica_source_url") == SOURCE_URL
    assert enriched.get("fragrantica_raw_payload_ref") == RAW_PAYLOAD_REF


def test_enricher_does_not_mutate_original(base_perfume_record: dict, normalized: dict) -> None:
    original_copy = dict(base_perfume_record)
    FragranticaEnricher().enrich(base_perfume_record, normalized)
    assert base_perfume_record == original_copy


def test_normalizer_preserves_source_url(parsed: dict) -> None:
    normalized = FragranticaNormalizer().normalize(parsed, RAW_PAYLOAD_REF)
    assert normalized.source_url == SOURCE_URL


def test_normalizer_preserves_raw_payload_ref(parsed: dict) -> None:
    normalized = FragranticaNormalizer().normalize(parsed, RAW_PAYLOAD_REF)
    assert normalized.raw_payload_ref == RAW_PAYLOAD_REF


def test_normalizer_has_normalized_at(parsed: dict) -> None:
    normalized = FragranticaNormalizer().normalize(parsed, RAW_PAYLOAD_REF)
    assert normalized.normalized_at is not None
    assert isinstance(normalized.normalized_at, str)


def test_enrichment_with_empty_fragrantica_record(base_perfume_record: dict) -> None:
    """Enricher must not crash when fragrantica_record is empty."""
    enriched = FragranticaEnricher().enrich(base_perfume_record, {})
    assert enriched["canonical_name"] == "Parfums de Marly Delina"
    assert "accords" not in enriched
