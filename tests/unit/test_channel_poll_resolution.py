"""Regression tests for channel_poll title-only resolver gating.

Covers:
  _resolver_input() — gating function that limits resolver input to title for
                      channel_poll items and leaves other methods unchanged.

Key regressions:
  1. Boilerplate description containing "cologne", "Don", "Divine", digit strings
     "11"/"21" in affiliate URLs must NOT create entity links for channel_poll items.
  2. A title like "RATING EVERY DIOR SAUVAGE" MUST still resolve Dior Sauvage
     via title-only input.
  3. search ingestion_method is completely unaffected — full text_content used.
  4. Items with no ingestion_method (legacy / default) are treated as search —
     full text_content used.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.ingest_youtube_channels import _resolver_input


# ---------------------------------------------------------------------------
# _resolver_input — gating correctness
# ---------------------------------------------------------------------------

class TestResolverInput:
    """Tests for the _resolver_input() gating function."""

    # ------------------------------------------------------------------
    # channel_poll: text_content must be replaced with title
    # ------------------------------------------------------------------

    def test_channel_poll_uses_title_as_text_content(self):
        """channel_poll item: text_content in resolver input must equal title."""
        item = {
            "id": "abc123",
            "title": "RATING EVERY DIOR SAUVAGE",
            "text_content": (
                "Welcome to my channel! If you haven't subscribed yet, please do.\n"
                "Where I Buy Fragrances: https://fragrantica.com/cologne-guide\n"
                "Support me: https://affiliate.example.com/shop/11/cologne-divine-don"
            ),
            "ingestion_method": "channel_poll",
        }
        result = _resolver_input(item)
        assert result["text_content"] == "RATING EVERY DIOR SAUVAGE"

    def test_channel_poll_boilerplate_description_stripped_from_resolver_input(self):
        """Description footer with cologne/Don/Divine/11/21 is not in resolver input."""
        boilerplate = (
            "Welcome to Aromatix! If you ha... make sure you subscribe.\n"
            "Buy fragrances: https://fragrantica.com/search?q=cologne-divine-don-11-21\n"
            "My socials: https://instagram.com/aromatix"
        )
        item = {
            "id": "vid001",
            "title": "How to Layer Fragrances",
            "text_content": boilerplate,
            "ingestion_method": "channel_poll",
        }
        result = _resolver_input(item)
        # Description boilerplate must not appear in resolver input
        assert "cologne" not in result["text_content"]
        assert "Don" not in result["text_content"]
        assert "Divine" not in result["text_content"]
        assert "11" not in result["text_content"]
        assert "21" not in result["text_content"]
        # Only title survives
        assert result["text_content"] == "How to Layer Fragrances"

    def test_channel_poll_empty_title_yields_empty_string(self):
        """If title is None/empty, resolver input must be empty string (not description)."""
        item = {
            "id": "vid002",
            "title": None,
            "text_content": "cologne Don Divine 11 21 fragrance shop",
            "ingestion_method": "channel_poll",
        }
        result = _resolver_input(item)
        assert result["text_content"] == ""

    def test_channel_poll_does_not_mutate_original_item(self):
        """_resolver_input must return a new dict, not mutate the original."""
        original_desc = "cologne description"
        item = {
            "id": "vid003",
            "title": "Angel's Share Clone Wars",
            "text_content": original_desc,
            "ingestion_method": "channel_poll",
        }
        _ = _resolver_input(item)
        # Original item unchanged
        assert item["text_content"] == original_desc

    def test_channel_poll_title_with_real_perfume_name_is_preserved(self):
        """Title containing a real perfume name must be passed through."""
        item = {
            "id": "vid004",
            "title": "Angel's Share Clone Wars — Best Alternatives",
            "text_content": "Description with boilerplate cologne and Don and affiliate links.",
            "ingestion_method": "channel_poll",
        }
        result = _resolver_input(item)
        assert "Angel's Share" in result["text_content"]
        assert "boilerplate" not in result["text_content"]

    def test_channel_poll_other_fields_unchanged(self):
        """All fields except text_content must be preserved unchanged."""
        item = {
            "id": "vid005",
            "title": "Best Armaf Colognes 2026",
            "text_content": "Description boilerplate with cologne.",
            "ingestion_method": "channel_poll",
            "source_account_id": "UCxxxxxxx",
            "published_at": "2026-04-27T00:00:00Z",
        }
        result = _resolver_input(item)
        assert result["id"] == "vid005"
        assert result["ingestion_method"] == "channel_poll"
        assert result["source_account_id"] == "UCxxxxxxx"
        assert result["published_at"] == "2026-04-27T00:00:00Z"

    # ------------------------------------------------------------------
    # search: text_content must be unchanged
    # ------------------------------------------------------------------

    def test_search_item_text_content_unchanged(self):
        """search ingestion_method must use full text_content unchanged."""
        full_desc = "Dior Sauvage vs Creed Aventus — the ultimate comparison."
        item = {
            "id": "vid010",
            "title": "Top Fragrances 2026",
            "text_content": full_desc,
            "ingestion_method": "search",
        }
        result = _resolver_input(item)
        assert result["text_content"] == full_desc

    def test_search_item_returns_same_object(self):
        """search items must be returned as-is (same dict object, no copy)."""
        item = {
            "id": "vid011",
            "title": "Title",
            "text_content": "Some description",
            "ingestion_method": "search",
        }
        result = _resolver_input(item)
        assert result is item  # same object, no unnecessary copy

    # ------------------------------------------------------------------
    # Missing / legacy ingestion_method defaults to search behaviour
    # ------------------------------------------------------------------

    def test_no_ingestion_method_treated_as_search(self):
        """Items with no ingestion_method field must use full text_content."""
        full_desc = "Creed Aventus full review with longevity test."
        item = {
            "id": "vid012",
            "title": "Creed Aventus Review",
            "text_content": full_desc,
            # no ingestion_method key
        }
        result = _resolver_input(item)
        assert result["text_content"] == full_desc

    def test_none_ingestion_method_treated_as_search(self):
        """Items with ingestion_method=None must use full text_content."""
        full_desc = "MFK Baccarat Rouge 540 — review and clones."
        item = {
            "id": "vid013",
            "title": "Baccarat Rouge 540 Review",
            "text_content": full_desc,
            "ingestion_method": None,
        }
        result = _resolver_input(item)
        assert result["text_content"] == full_desc


# ---------------------------------------------------------------------------
# Regression scenarios — specific false-positive patterns from Aromatix / FB Fragrances
# ---------------------------------------------------------------------------

class TestBoilerplateFalsePositiveRegression:
    """Regression tests for the specific false-positive patterns observed in
    Aromatix and FB Fragrances ingestion runs (2026-04-30)."""

    AROMATIX_BOILERPLATE = (
        "Welcome back to Aromatix! If you haven't already, make sure you subscribe.\n"
        "Where I Usually Buy Fragrances (by ...):\n"
        "  https://fragrantica.com/search\n"
        "  https://parfumo.com/Don\n"
        "Etat Libre d'Orange Cologne Eau de Parfum shop: https://example.com/cologne\n"
        "Divine perfumes: https://shop.example.com/Divine\n"
    )

    FB_FRAGRANCES_BOILERPLATE = (
        "Where I Usually Buy Fragrances (by FB Fragrances):\n"
        "  https://affiliate.example.com/shop/11/fragrance-guide\n"
        "  https://affiliate.example.com/shop/21/cologne\n"
        "My socials: https://instagram.com/fbfragrances\n"
    )

    def _make_channel_poll_item(self, item_id: str, title: str, description: str) -> dict:
        return {
            "id": item_id,
            "title": title,
            "text_content": description,
            "ingestion_method": "channel_poll",
        }

    def test_aromatix_cologne_boilerplate_not_in_resolver_input(self):
        """'cologne' in Aromatix footer must not appear in resolver input."""
        item = self._make_channel_poll_item(
            "arx001",
            "The PERFECT Minimalist Fragrance Collection",
            self.AROMATIX_BOILERPLATE,
        )
        result = _resolver_input(item)
        assert "cologne" not in result["text_content"].lower()
        assert "Etat Libre" not in result["text_content"]

    def test_aromatix_don_boilerplate_not_in_resolver_input(self):
        """'Don' in Aromatix footer URL must not appear in resolver input."""
        item = self._make_channel_poll_item(
            "arx002",
            "Top 5 Office Fragrances for Men",
            self.AROMATIX_BOILERPLATE,
        )
        result = _resolver_input(item)
        assert "Don" not in result["text_content"]

    def test_aromatix_divine_boilerplate_not_in_resolver_input(self):
        """'Divine' in Aromatix footer must not appear in resolver input."""
        item = self._make_channel_poll_item(
            "arx003",
            "Best Blind Buys Under $50",
            self.AROMATIX_BOILERPLATE,
        )
        result = _resolver_input(item)
        assert "Divine" not in result["text_content"]

    def test_fb_fragrances_11_boilerplate_not_in_resolver_input(self):
        """'11' in FB Fragrances affiliate URL must not appear in resolver input."""
        item = self._make_channel_poll_item(
            "fbf001",
            "Fragrances I Used To Love",
            self.FB_FRAGRANCES_BOILERPLATE,
        )
        result = _resolver_input(item)
        assert "11" not in result["text_content"]

    def test_fb_fragrances_21_boilerplate_not_in_resolver_input(self):
        """'21' in FB Fragrances affiliate URL must not appear in resolver input."""
        item = self._make_channel_poll_item(
            "fbf002",
            "My Top 10 Niche Fragrances",
            self.FB_FRAGRANCES_BOILERPLATE,
        )
        result = _resolver_input(item)
        assert "21" not in result["text_content"]

    def test_valid_dior_sauvage_title_resolves_via_title(self):
        """Title 'RATING EVERY DIOR SAUVAGE' must survive into resolver input."""
        item = self._make_channel_poll_item(
            "arx004",
            "RATING EVERY DIOR SAUVAGE",
            self.AROMATIX_BOILERPLATE,
        )
        result = _resolver_input(item)
        assert "DIOR SAUVAGE" in result["text_content"]

    def test_valid_angels_share_title_resolves_via_title(self):
        """Title "Angel's Share Clone War" must survive into resolver input."""
        item = self._make_channel_poll_item(
            "arx005",
            "Angel's Share Clone War — Best Alternatives 2026",
            self.AROMATIX_BOILERPLATE,
        )
        result = _resolver_input(item)
        assert "Angel's Share" in result["text_content"]

    def test_valid_armaf_club_de_nuit_title_resolves_via_title(self):
        """Title mentioning Club de Nuit must survive into resolver input."""
        item = self._make_channel_poll_item(
            "arx006",
            "Armaf Club de Nuit Intense Man — Beginner Guide",
            self.AROMATIX_BOILERPLATE,
        )
        result = _resolver_input(item)
        assert "Club de Nuit" in result["text_content"]

    def test_search_item_with_description_containing_entities_unaffected(self):
        """search items with entity names in description must still resolve from description."""
        item = {
            "id": "srch001",
            "title": "Fragrance Review",
            "text_content": (
                "In this video I review Dior Sauvage vs Creed Aventus and compare "
                "longevity, projection, and sillage of both fragrances."
            ),
            "ingestion_method": "search",
        }
        result = _resolver_input(item)
        # Full description preserved
        assert "Dior Sauvage" in result["text_content"]
        assert "Creed Aventus" in result["text_content"]
        assert "longevity" in result["text_content"]
