"""Regression tests for channel_poll title-only resolver gating and single-word
alias safety guards.

Covers:
  _resolver_input() — gating function that limits resolver input to title for
                      channel_poll items and leaves other methods unchanged.

  Resolver single-word alias guards (PerfumeResolver.resolve_text):
    _CONTRACTION_TAILS — tokens immediately following a single-word alias hit
                         that indicate the token came from a split contraction
                         (e.g. "don't" → ["don", "t"]) and must not match.
    _BLOCKED_SINGLE_WORD_ALIASES — explicit set of single-word alias strings
                         too generic/ambiguous to match in social text.

Key regressions:
  1. Boilerplate description containing "cologne", "Don", "Divine", digit strings
     "11"/"21" in affiliate URLs must NOT create entity links for channel_poll items.
  2. A title like "RATING EVERY DIOR SAUVAGE" MUST still resolve Dior Sauvage
     via title-only input.
  3. search ingestion_method is completely unaffected — full text_content used.
  4. Items with no ingestion_method (legacy / default) are treated as search —
     full text_content used.
  5. "Don't Blind Buy These Fragrances" must NOT resolve Xerjoff Join the Club Don.
  6. "Pink eye again #cologne #fragrances" must NOT resolve Nanadebary Pink.
  7. Multi-token title matches (Dior Sauvage, YSL Libre) must still work.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.ingest_youtube_channels import _resolver_input
from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import (
    _BLOCKED_SINGLE_WORD_ALIASES,
    _CONTRACTION_TAILS,
)
from perfume_trend_sdk.utils.alias_generator import normalize_text


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


# ---------------------------------------------------------------------------
# Single-word alias safety guards — unit tests
# ---------------------------------------------------------------------------

def _simulate_resolve_text_single_word(text: str) -> list[str]:
    """
    Simulate the part of resolve_text() that applies single-word alias guards.

    Returns the list of single-token phrases that WOULD be looked up in the
    alias store (i.e. phrases that pass both guards).  We don't need a real DB
    to test the guard logic — we just check which phrases survive.
    """
    normalized = normalize_text(text)
    tokens = normalized.split()
    surviving = []
    for i, tok in enumerate(tokens):
        # Contraction-tail guard
        if i + 1 < len(tokens) and tokens[i + 1] in _CONTRACTION_TAILS:
            continue
        # Blocked single-word aliases guard
        if tok in _BLOCKED_SINGLE_WORD_ALIASES:
            continue
        surviving.append(tok)
    return surviving


class TestResolverSingleWordGuards:
    """Tests for the contraction-tail and blocked-alias guards in resolve_text()."""

    # ------------------------------------------------------------------
    # Contraction-tail guard
    # ------------------------------------------------------------------

    def test_dont_contraction_strips_don_token(self):
        """'don't' normalises to ['don', 't'] — 'don' must be blocked by contraction guard."""
        survivors = _simulate_resolve_text_single_word("don't")
        assert "don" not in survivors, (
            "'don' from \"don't\" must be blocked by the contraction-tail guard"
        )

    def test_dont_blind_buy_contraction_guard(self):
        """Full channel_poll regression: title with 'don't' must not pass 'don' to alias lookup."""
        survivors = _simulate_resolve_text_single_word(
            "Don't Blind Buy These Fragrances"
        )
        assert "don" not in survivors

    def test_dont_regression_aromatix(self):
        """Aromatix regression: 'Don't Blind Buy… Unless It's THESE 9 Fragrances'."""
        survivors = _simulate_resolve_text_single_word(
            "Don't Blind Buy… Unless It's THESE 9 Fragrances🔥 (Under $100)"
        )
        assert "don" not in survivors

    def test_dont_regression_fb_fragrances_men(self):
        """FB Fragrances regression: 'And they say men don't make hard decisions'."""
        survivors = _simulate_resolve_text_single_word(
            "And they say men don't make hard decisions #cologne #fragrance"
        )
        assert "don" not in survivors

    def test_dont_regression_fb_fragrances_blind_buy(self):
        """FB Fragrances regression: blind buy title with 'don't'."""
        survivors = _simulate_resolve_text_single_word(
            "I Blind Bought 7 Viral Clone Fragrances (Vol. 3) So You Don't Have To"
        )
        assert "don" not in survivors

    def test_contraction_tails_coverage(self):
        """Verify the contraction-tail set covers the most common English contractions."""
        required_tails = {"t", "nt", "s", "ll", "re", "ve", "d", "m"}
        missing = required_tails - _CONTRACTION_TAILS
        assert not missing, f"Missing contraction tails: {missing}"

    # ------------------------------------------------------------------
    # Blocked single-word aliases guard
    # ------------------------------------------------------------------

    def test_pink_blocked_in_unrelated_title(self):
        """'Pink eye again' must NOT pass 'pink' to the alias lookup."""
        survivors = _simulate_resolve_text_single_word(
            "Pink eye again #cologne #fragrances"
        )
        assert "pink" not in survivors

    def test_don_blocked_standalone(self):
        """Standalone 'don' (not followed by contraction tail) must still be blocked."""
        survivors = _simulate_resolve_text_single_word("Don is a great fragrance")
        assert "don" not in survivors

    def test_numeric_11_blocked(self):
        """'11' in titles (prices, ratings, counts) must be blocked."""
        survivors = _simulate_resolve_text_single_word("Top 11 Fragrances Under $100")
        assert "11" not in survivors

    def test_numeric_21_blocked(self):
        """'21' in affiliate URL fragments must be blocked."""
        survivors = _simulate_resolve_text_single_word(
            "shop/21/cologne-guide fragrance haul"
        )
        assert "21" not in survivors

    def test_blocked_aliases_set_contains_required_words(self):
        """The blocklist must contain all user-specified problematic single-word aliases."""
        required = {"don", "pink", "11", "21", "dot", "smart", "standard",
                    "heritage", "moth", "jack", "man"}
        missing = required - _BLOCKED_SINGLE_WORD_ALIASES
        assert not missing, f"Missing from blocked alias set: {missing}"

    # ------------------------------------------------------------------
    # Multi-token aliases must still pass through (guards do NOT affect size ≥ 2)
    # ------------------------------------------------------------------

    def test_dior_sauvage_tokens_not_blocked(self):
        """'Dior Sauvage' is multi-token — individual tokens must survive for window matching."""
        survivors = _simulate_resolve_text_single_word(
            "RATING EVERY DIOR SAUVAGE IN 2026"
        )
        # "dior" and "sauvage" are not in the blocked set and not contraction artifacts
        assert "dior" in survivors
        assert "sauvage" in survivors

    def test_ysl_libre_tokens_not_blocked(self):
        """'YSL Libre' tokens must survive the single-word guards."""
        survivors = _simulate_resolve_text_single_word(
            "The new YSL Libre Berry Crush fragrance review"
        )
        assert "ysl" in survivors
        assert "libre" in survivors

    def test_creed_aventus_tokens_not_blocked(self):
        """'Creed Aventus' tokens must survive."""
        survivors = _simulate_resolve_text_single_word("Top Creed Aventus alternatives 2026")
        assert "creed" in survivors
        assert "aventus" in survivors

    def test_angels_share_tokens_not_blocked(self):
        """'Angels Share' tokens must survive.

        normalize_text("Angel's") strips the possessive 's → "angel" (not "angels").
        The alias in the resolver is "angels share" (generated from the canonical name).
        Both individual tokens must survive single-word guards so the 2-token window
        "angel share" can be attempted.
        """
        survivors = _simulate_resolve_text_single_word(
            "Angel's Share Clone War — Best Alternatives 2026"
        )
        # "Angel's" → normalize_text strips 's → "angel" (not "angels")
        assert "angel" in survivors
        assert "share" in survivors

    def test_armaf_club_de_nuit_tokens_not_blocked(self):
        """'Armaf Club de Nuit' tokens must survive."""
        survivors = _simulate_resolve_text_single_word(
            "Armaf Club de Nuit Intense Man — Beginner Guide"
        )
        assert "armaf" in survivors
        assert "club" in survivors
        assert "nuit" in survivors
