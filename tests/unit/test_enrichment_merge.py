from __future__ import annotations

import pytest

from perfume_trend_sdk.enrichers.perfume_metadata.fragrantica_enricher import (
    FragranticaEnricher,
)


@pytest.fixture()
def base_record() -> dict:
    return {
        "fragrance_id": "pdm-delina-001",
        "canonical_name": "Parfums de Marly Delina",
        "normalized_name": "parfums de marly delina",
        "brand_id": 42,
        "perfume_id": 99,
    }


@pytest.fixture()
def fragrantica_with_notes() -> dict:
    return {
        "notes_top": ["bergamot", "lychee", "rhubarb"],
        "notes_middle": ["rose", "peony", "iso e super"],
        "notes_base": ["musk", "vanilla", "cashmeran"],
        "accords": ["floral", "sweet", "powdery"],
        "rating_value": 4.2,
        "rating_count": 12345,
        "source_url": "https://www.fragrantica.com/perfume/test.html",
        "raw_payload_ref": "data/raw/fragrantica/00001.json",
    }


def test_enricher_adds_official_notes(base_record, fragrantica_with_notes):
    enriched = FragranticaEnricher().enrich(base_record, fragrantica_with_notes)

    assert "official_notes" in enriched
    assert enriched["official_notes"]["top"] == ["bergamot", "lychee", "rhubarb"]
    assert enriched["official_notes"]["middle"] == ["rose", "peony", "iso e super"]
    assert enriched["official_notes"]["base"] == ["musk", "vanilla", "cashmeran"]


def test_enricher_official_notes_structure(base_record, fragrantica_with_notes):
    enriched = FragranticaEnricher().enrich(base_record, fragrantica_with_notes)

    notes = enriched["official_notes"]
    assert isinstance(notes, dict)
    assert set(notes.keys()) == {"top", "middle", "base"}
    for tier in ("top", "middle", "base"):
        assert isinstance(notes[tier], list)


def test_enricher_official_notes_idempotent(base_record, fragrantica_with_notes):
    """Calling enrich twice with the same inputs must produce identical output."""
    enricher = FragranticaEnricher()
    first = enricher.enrich(base_record, fragrantica_with_notes)
    second = enricher.enrich(base_record, fragrantica_with_notes)

    assert first["official_notes"] == second["official_notes"]


def test_enricher_official_notes_skipped_when_all_empty(base_record):
    """official_notes must NOT be added when all note lists are empty."""
    fragrantica_empty_notes = {
        "notes_top": [],
        "notes_middle": [],
        "notes_base": [],
        "source_url": "https://fragrantica.com/test",
        "raw_payload_ref": "ref",
    }
    enriched = FragranticaEnricher().enrich(base_record, fragrantica_empty_notes)
    assert "official_notes" not in enriched


def test_enricher_official_notes_partial(base_record):
    """official_notes added when only some tiers are present."""
    fragrantica = {
        "notes_top": ["lemon"],
        "notes_middle": [],
        "notes_base": [],
        "source_url": "https://fragrantica.com/test",
        "raw_payload_ref": "ref",
    }
    enriched = FragranticaEnricher().enrich(base_record, fragrantica)
    assert "official_notes" in enriched
    assert enriched["official_notes"]["top"] == ["lemon"]
    assert enriched["official_notes"]["middle"] == []
    assert enriched["official_notes"]["base"] == []


def test_enricher_does_not_mutate_base_record(base_record, fragrantica_with_notes):
    original = dict(base_record)
    FragranticaEnricher().enrich(base_record, fragrantica_with_notes)
    assert base_record == original


def test_enricher_protected_fields_unchanged(base_record, fragrantica_with_notes):
    enriched = FragranticaEnricher().enrich(base_record, fragrantica_with_notes)
    assert enriched["canonical_name"] == "Parfums de Marly Delina"
    assert enriched["brand_id"] == 42
    assert enriched["perfume_id"] == 99


def test_enricher_official_notes_as_copy(base_record, fragrantica_with_notes):
    """Modifying the returned official_notes must not affect the original input."""
    enriched = FragranticaEnricher().enrich(base_record, fragrantica_with_notes)
    enriched["official_notes"]["top"].append("INJECTED")

    # Re-enrich — original fragrantica_with_notes must be unchanged
    enriched2 = FragranticaEnricher().enrich(base_record, fragrantica_with_notes)
    assert "INJECTED" not in enriched2["official_notes"]["top"]
