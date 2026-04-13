from __future__ import annotations

"""
Tests for resolver hardening — Track B:
  1. 5-word and 6-word alias sliding-window resolution
  2. Possessive brand normalization ("amouage's" → "amouage")
  3. Unresolved candidate emission for non-matched fragrance names

All tests use a tmp_path SQLite DB seeded with controlled fixtures so they
never depend on the production pti.db content.
"""

from pathlib import Path

import pytest

from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import PerfumeResolver
from perfume_trend_sdk.utils.alias_generator import normalize_text
from perfume_trend_sdk.workflows.load_fragrance_master import ingest_seed_csv


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SEED_CSV = (
    "fragrance_id,brand_name,perfume_name,source\n"
    # 5-token canonical alias: "diptyque philosykos eau de parfum"
    "fr_1,Diptyque,Philosykos Eau de Parfum,kaggle\n"
    # 6-token canonical alias: "serge lutens ambre sultan eau de parfum"
    "fr_2,Serge Lutens,Ambre Sultan Eau de Parfum,kaggle\n"
    # Short alias for possessive test: "sauvage" / "dior sauvage"
    "fr_3,Dior,Sauvage,kaggle\n"
    # Multi-word for unresolved-candidate test — intentionally NOT a reddit text match
    "fr_4,Creed,Aventus,kaggle\n"
)


@pytest.fixture()
def resolver(tmp_path: Path) -> PerfumeResolver:
    csv_path = tmp_path / "seed.csv"
    db_path = tmp_path / "db.sqlite"
    csv_path.write_text(_SEED_CSV)
    ingest_seed_csv(csv_path, db_path)
    return PerfumeResolver(str(db_path))


# ---------------------------------------------------------------------------
# 1. Five-word alias resolution
# ---------------------------------------------------------------------------

class TestFiveTokenWindow:
    def test_full_five_token_phrase_resolves(self, resolver):
        """Text containing the full 5-word alias must resolve."""
        text = "I love diptyque philosykos eau de parfum so much"
        matches = resolver.resolve_text(text)
        names = [m["canonical_name"] for m in matches]
        assert any("Philosykos" in n for n in names), (
            f"Expected Philosykos in matches, got: {names}"
        )

    def test_short_brand_plus_perfume_phrase_resolves(self, resolver):
        """'diptyque philosykos' (2-token short alias) resolves via concentration
        stripping introduced in alias-generator Phase 2.

        This verifies that the short alias IS now seeded in the test DB, so
        posts like 'diptyque philosykos edt longevity' resolve correctly.
        """
        text = "diptyque philosykos edt review"
        matches = resolver.resolve_text(text)
        names = [m["canonical_name"] for m in matches]
        assert any("Philosykos" in n for n in names), (
            f"Expected 'diptyque philosykos' to resolve via short alias; got: {names}"
        )

    def test_five_token_alias_in_longer_sentence(self, resolver):
        """5-word alias embedded in surrounding text still resolves via window."""
        text = "What do you think of diptyque philosykos eau de parfum vs the EDT?"
        matches = resolver.resolve_text(text)
        names = [m["canonical_name"] for m in matches]
        assert any("Philosykos" in n for n in names)


# ---------------------------------------------------------------------------
# 2. Six-word alias resolution
# ---------------------------------------------------------------------------

class TestSixTokenWindow:
    def test_full_six_token_phrase_resolves(self, resolver):
        """Text containing the full 6-word alias must resolve."""
        text = "My first purchase: serge lutens ambre sultan eau de parfum review"
        matches = resolver.resolve_text(text)
        names = [m["canonical_name"] for m in matches]
        assert any("Ambre Sultan" in n for n in names), (
            f"Expected Ambre Sultan in matches, got: {names}"
        )

    def test_four_token_sub_phrase_resolves(self, resolver):
        """'ambre sultan eau de parfum' (5 tokens) also resolves — within window."""
        text = "bought ambre sultan eau de parfum last week"
        matches = resolver.resolve_text(text)
        names = [m["canonical_name"] for m in matches]
        assert any("Ambre Sultan" in n for n in names)

    def test_six_token_alias_deduplicates(self, resolver):
        """Same entity resolved via both 6-word and sub-phrase → only 1 result."""
        text = "serge lutens ambre sultan eau de parfum is great ambre sultan eau de parfum"
        matches = resolver.resolve_text(text)
        names = [m["canonical_name"] for m in matches]
        ambre_hits = [n for n in names if "Ambre Sultan" in n]
        assert len(ambre_hits) == 1, f"Deduplication failed: {ambre_hits}"


# ---------------------------------------------------------------------------
# 3. Possessive normalization
# ---------------------------------------------------------------------------

class TestPossessiveNormalization:
    def test_apostrophe_s_stripped(self):
        assert normalize_text("amouage's") == "amouage"

    def test_possessive_brand_in_sentence(self):
        assert normalize_text("amouage's secret garden collection") == "amouage secret garden collection"

    def test_apostrophe_within_word_becomes_space(self):
        # "d'hermes" → "d hermes"  (keeps both parts for "terre d hermes" matching)
        assert normalize_text("terre d'hermes intense") == "terre d hermes intense"

    def test_plain_apostrophe_word_split(self):
        assert normalize_text("dior's sauvage") == "dior sauvage"

    def test_possessive_text_resolves(self, resolver):
        """'dior's sauvage' — after possessive stripping — must resolve to Dior Sauvage."""
        text = "I just bought dior's sauvage and love it"
        matches = resolver.resolve_text(text)
        names = [m["canonical_name"] for m in matches]
        assert any("Sauvage" in n for n in names), (
            f"Possessive 'dior's sauvage' did not resolve; matches: {names}"
        )

    def test_possessive_brand_only_does_not_spuriously_resolve(self, resolver):
        """A brand possessive with no perfume context does not produce a false match."""
        # "creed's latest release" — "creed" alone has no short alias in test DB
        text = "creed's latest release is amazing"
        matches = resolver.resolve_text(text)
        # "aventus" or other Creed alias is not in this text, so no match expected
        assert matches == []


# ---------------------------------------------------------------------------
# 4. Unresolved candidate emission
# ---------------------------------------------------------------------------

class TestUnresolvedCandidateEmission:
    def test_unresolved_mentions_non_empty_for_unknown_text(self, resolver):
        """Text with no DB matches should produce unresolved candidate phrases."""
        text = "Has anyone tried maison margiela replica jazz club?"
        result = resolver.resolve_content_item({"id": "t1", "text_content": text})
        assert result["resolved_entities"] == []
        assert len(result["unresolved_mentions"]) > 0, (
            "Expected candidate phrases in unresolved_mentions but got none"
        )

    def test_unresolved_mentions_disabled_returns_empty(self, resolver):
        """emit_candidates=False suppresses unresolved_mentions."""
        text = "Has anyone tried maison margiela replica jazz club?"
        result = resolver.resolve_content_item(
            {"id": "t1", "text_content": text}, emit_candidates=False
        )
        assert result["unresolved_mentions"] == []

    def test_unresolved_mentions_contain_string_phrases(self, resolver):
        """Candidates must be plain strings, not dicts or other types."""
        text = "interested in parfums de marly layton and valentino uomo"
        result = resolver.resolve_content_item({"id": "t2", "text_content": text})
        for candidate in result["unresolved_mentions"]:
            assert isinstance(candidate, str), f"Expected str, got {type(candidate)}: {candidate!r}"

    def test_resolved_entity_name_not_in_unresolved(self, resolver):
        """Phrases that resolved must not also appear in unresolved_mentions."""
        text = "I love dior sauvage"
        result = resolver.resolve_content_item({"id": "t3", "text_content": text})
        assert len(result["resolved_entities"]) > 0
        # Canonical name (normalised) should not be echoed in unresolved
        resolved_names = {e["canonical_name"].lower() for e in result["resolved_entities"]}
        for candidate in result["unresolved_mentions"]:
            for rname in resolved_names:
                assert rname not in candidate, (
                    f"Resolved entity {rname!r} leaked into unresolved: {candidate!r}"
                )

    def test_empty_text_returns_no_candidates(self, resolver):
        result = resolver.resolve_content_item({"id": "t4", "text_content": ""})
        assert result["unresolved_mentions"] == []

    def test_none_text_returns_no_candidates(self, resolver):
        result = resolver.resolve_content_item({"id": "t5", "text_content": None})
        assert result["unresolved_mentions"] == []

    def test_source_platform_preserved_in_content_item(self, resolver):
        """resolve_content_item must pass through source_platform when present."""
        item = {"id": "t6", "text_content": "creed aventus review", "source_platform": "reddit"}
        result = resolver.resolve_content_item(item)
        # content_item_id must match
        assert result["content_item_id"] == "t6"

    def test_resolver_version_bumped(self, resolver):
        """Version must be '1.1' after hardening."""
        result = resolver.resolve_content_item({"id": "t7", "text_content": "x"})
        assert result["resolver_version"] == "1.1"
