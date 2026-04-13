from __future__ import annotations

from pathlib import Path

import pytest

from perfume_trend_sdk.connectors.fragrantica.parser import FragranticaParser

FIXTURE_PATH = Path(__file__).parent.parent.parent / "fixtures" / "fragrantica_perfume_page.html"
SOURCE_URL = "https://www.fragrantica.com/perfume/Parfums-de-Marly/Delina-38737.html"


@pytest.fixture(scope="module")
def fixture_html() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parsed(fixture_html: str) -> dict:
    return FragranticaParser().parse(fixture_html, SOURCE_URL)


def test_parse_brand_name(parsed: dict) -> None:
    assert parsed["brand_name"] == "Parfums de Marly"


def test_parse_perfume_name(parsed: dict) -> None:
    assert parsed["perfume_name"] == "Delina"


def test_parse_accords(parsed: dict) -> None:
    assert isinstance(parsed["accords"], list)
    assert "floral" in parsed["accords"]


def test_parse_notes_top(parsed: dict) -> None:
    assert isinstance(parsed["notes_top"], list)
    assert len(parsed["notes_top"]) > 0


def test_parse_notes_middle(parsed: dict) -> None:
    assert isinstance(parsed["notes_middle"], list)
    assert len(parsed["notes_middle"]) > 0


def test_parse_notes_base(parsed: dict) -> None:
    assert isinstance(parsed["notes_base"], list)
    assert len(parsed["notes_base"]) > 0


def test_parse_rating(parsed: dict) -> None:
    assert isinstance(parsed["rating_value"], float)
    assert isinstance(parsed["rating_count"], int)
    assert parsed["rating_value"] == pytest.approx(4.28)
    assert parsed["rating_count"] == 1842


def test_parse_source_url_preserved(parsed: dict) -> None:
    assert parsed["source_url"] == SOURCE_URL


def test_parse_release_year(parsed: dict) -> None:
    assert parsed["release_year"] == 2017


def test_parse_gender(parsed: dict) -> None:
    assert parsed["gender"] == "women"


def test_parse_tolerates_empty_html() -> None:
    """Parser must return a dict and never raise on empty HTML."""
    result = FragranticaParser().parse("", "http://x.com")
    assert isinstance(result, dict)
    assert result["brand_name"] is None
    assert result["perfume_name"] is None
    assert result["accords"] == []
    assert result["notes_top"] == []
    assert result["notes_middle"] == []
    assert result["notes_base"] == []
    assert result["rating_value"] is None
    assert result["rating_count"] is None


def test_parse_tolerates_garbage_html() -> None:
    """Parser must return a dict and never raise on malformed HTML."""
    result = FragranticaParser().parse("<html><body>GARBAGE</body></html>", "http://x.com")
    assert isinstance(result, dict)
