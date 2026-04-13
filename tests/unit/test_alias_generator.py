from perfume_trend_sdk.utils.alias_generator import (
    generate_brand_aliases,
    generate_perfume_aliases,
    normalize_text,
)


def test_normalize_text_basic() -> None:
    assert normalize_text("  Baccarat Rouge 540! ") == "baccarat rouge 540"


def test_generate_brand_aliases_with_known_abbreviation() -> None:
    aliases = generate_brand_aliases("Parfums de Marly")
    assert "parfums de marly" in aliases
    assert "pdm" in aliases


def test_generate_perfume_aliases_basic() -> None:
    aliases = generate_perfume_aliases("Parfums de Marly", "Delina")
    assert "delina" in aliases
    assert "parfums de marly delina" in aliases
    assert "delina perfume" in aliases
    assert "pdm delina" in aliases


def test_generate_perfume_aliases_without_known_abbreviation() -> None:
    aliases = generate_perfume_aliases("Byredo", "Gypsy Water")
    assert "gypsy water" in aliases
    assert "byredo gypsy water" in aliases
    assert "gypsy water perfume" in aliases
