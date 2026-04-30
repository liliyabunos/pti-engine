"""Unit tests for transcript queue classification logic.

Covers:
  _text_without_urls()         — URL stripping helper
  _has_fragrance_context()     — fragrance-term detection after URL strip
  _classify_transcript_priority() — end-to-end queue classification

Key regression:
  Gentlemen's Gazette videos must NOT be marked needed/high solely because
  their description footer contains a URL with the word 'fragrance' in it.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.ingest_youtube_channels import (
    _classify_transcript_priority,
    _has_fragrance_context,
    _text_without_urls,
)


# ---------------------------------------------------------------------------
# _text_without_urls
# ---------------------------------------------------------------------------

class TestTextWithoutUrls:
    def test_removes_https_url(self):
        result = _text_without_urls("visit https://example.com/fragrance-shop now")
        assert "https://" not in result
        assert "fragrance-shop" not in result

    def test_removes_http_url(self):
        result = _text_without_urls("http://old-site.com/cologne-guide")
        assert "http://" not in result

    def test_removes_gazette_boilerplate_url(self):
        gazette_footer = (
            "→ accessories: https://gentl.mn/accessories-clothing-fragrance01\n"
            "→ instagram: https://instagram.com/gentlemansgazette"
        )
        result = _text_without_urls(gazette_footer)
        # URL-embedded word 'fragrance' is gone
        assert "fragrance" not in result
        # The Instagram URL itself is gone, but the label "→ instagram:" stays — that's correct
        assert "instagram.com" not in result
        assert "gentlemansgazette" not in result

    def test_preserves_text_without_urls(self):
        text = "best fragrance for summer 2026"
        assert _text_without_urls(text) == text

    def test_removes_url_leaves_surrounding_text(self):
        result = _text_without_urls("great cologne https://shop.com/cologne and more")
        assert "great cologne" in result
        assert "and more" in result
        assert "https://" not in result

    def test_empty_string(self):
        assert _text_without_urls("") == ""

    def test_only_url(self):
        result = _text_without_urls("https://gentl.mn/accessories-clothing-fragrance01")
        assert result.strip() == ""


# ---------------------------------------------------------------------------
# _has_fragrance_context
# ---------------------------------------------------------------------------

def _make_item(title: str = "", description: str = "") -> dict:
    return {
        "search_item": {
            "snippet": {"title": title, "description": description}
        },
        "video_details": {"contentDetails": {"duration": "PT10M"}},
    }


class TestHasFragranceContext:
    def test_url_only_fragrance_word_is_not_context(self):
        """Core regression: boilerplate URL must not trigger fragrance match."""
        item = _make_item(
            title="How To Tie The Easiest Tie Knot",
            description=(
                "→ accessories: https://gentl.mn/accessories-clothing-fragrance01\n"
                "→ instagram: https://instagram.com/gentlemansgazette"
            ),
        )
        assert _has_fragrance_context(item) is False

    def test_real_fragrance_content_matches(self):
        item = _make_item(title="best fragrance for summer", description="")
        assert _has_fragrance_context(item) is True

    def test_fragrance_in_description_text_matches(self):
        item = _make_item(
            title="Style tips for men",
            description="I love wearing a good fragrance with this look.",
        )
        assert _has_fragrance_context(item) is True

    def test_perfume_review_title(self):
        item = _make_item(title="Creed Aventus Perfume Review 2026", description="")
        assert _has_fragrance_context(item) is True

    def test_cologne_in_title(self):
        item = _make_item(title="Best Cologne for Work 2026", description="")
        assert _has_fragrance_context(item) is True

    def test_generic_menswear_video(self):
        item = _make_item(
            title="11 Vintage Wedding Outfit Ideas For Men",
            description="Tips on suits, shoes, and accessories.",
        )
        assert _has_fragrance_context(item) is False

    def test_url_fragrance_plus_real_fragrance_text(self):
        """URL with 'fragrance' AND real fragrance text → True (text is the actual trigger)."""
        item = _make_item(
            title="Cologne recommendation",
            description=(
                "My pick: https://gentl.mn/accessories-clothing-fragrance01\n"
                "This cologne is a must-have."
            ),
        )
        assert _has_fragrance_context(item) is True

    def test_oud_term(self):
        item = _make_item(title="The best oud fragrances for winter", description="")
        assert _has_fragrance_context(item) is True

    def test_baccarat_rouge_in_title(self):
        item = _make_item(title="Baccarat Rouge 540 review — is it worth it?", description="")
        assert _has_fragrance_context(item) is True

    def test_blind_buy_in_description(self):
        item = _make_item(title="Top 5 picks", description="These are great blind buy choices.")
        assert _has_fragrance_context(item) is True

    def test_case_insensitive_match(self):
        item = _make_item(title="BEST PERFUME 2026", description="")
        assert _has_fragrance_context(item) is True

    def test_fragranceone_brand(self):
        """Jeremy Fragrance's own brand name should match."""
        item = _make_item(title="New fragranceone drop!", description="")
        assert _has_fragrance_context(item) is True


# ---------------------------------------------------------------------------
# _classify_transcript_priority  (end-to-end)
# ---------------------------------------------------------------------------

JEREMY_CHANNEL = {
    "channel_id": "UCzKrJ5NSA9o7RHYRG12kHZw",
    "title": "Jeremy Fragrance",
    "quality_tier": "tier_1",
    "category": "reviewer",
}

GAZETTE_CHANNEL = {
    "channel_id": "UCEgoThiTZG6wbTVA6B1Ksaw",
    "title": "Gentlemen's Gazette",
    "quality_tier": "tier_3",
    "category": "beauty",
}


class TestClassifyTranscriptPriority:
    # ------------------------------------------------------------------ Jeremy
    def test_jeremy_tier1_any_video_is_high(self):
        """tier_1 → needed/high regardless of content."""
        item = _make_item(title="Style tips", description="")
        status, priority = _classify_transcript_priority(item, JEREMY_CHANNEL)
        assert (status, priority) == ("needed", "high")

    def test_jeremy_short_with_empty_description_is_high(self):
        """Shorts with empty metadata still qualify via tier_1 rule."""
        item = _make_item(title="🔥 #Shorts", description="")
        item["video_details"]["contentDetails"]["duration"] = "PT30S"
        status, priority = _classify_transcript_priority(item, JEREMY_CHANNEL)
        assert (status, priority) == ("needed", "high")

    def test_jeremy_reviewer_category_is_high(self):
        """category=reviewer fires even if tier is somehow stripped."""
        channel = dict(JEREMY_CHANNEL, quality_tier="unrated")
        item = _make_item(title="some video", description="")
        status, priority = _classify_transcript_priority(item, channel)
        assert (status, priority) == ("needed", "high")

    # ------------------------------------------------------------------ Gazette
    def test_gazette_url_only_fragrance_not_queued(self):
        """Core regression: boilerplate footer URL must NOT queue the video."""
        item = _make_item(
            title="How To Tie The Easiest Tie Knot",
            description=(
                "Tips on tie knots.\n"
                "→ accessories: https://gentl.mn/accessories-clothing-fragrance01\n"
                "→ instagram: https://instagram.com/gentlemansgazette"
            ),
        )
        status, priority = _classify_transcript_priority(item, GAZETTE_CHANNEL)
        assert (status, priority) == ("none", "none")

    def test_gazette_real_fragrance_content_queued(self):
        """Gazette video genuinely about fragrance should be queued."""
        item = _make_item(
            title="The Best Cologne for a Job Interview",
            description="A guide to choosing the right fragrance for professional settings.",
        )
        status, priority = _classify_transcript_priority(item, GAZETTE_CHANNEL)
        assert (status, priority) == ("needed", "high")

    def test_gazette_non_fragrance_fashion_not_queued(self):
        """Pure fashion video with no fragrance terms → not queued."""
        item = _make_item(
            title="11 Vintage Wedding Outfit Ideas For Men",
            description="Suits, shoes, and accessories advice. https://gentl.mn/suits",
        )
        status, priority = _classify_transcript_priority(item, GAZETTE_CHANNEL)
        assert (status, priority) == ("none", "none")

    def test_gazette_clothes_moths_not_queued(self):
        """URL-stripping prevents 'fragrance' in footer URL from matching."""
        item = _make_item(
            title="My Clothes Moths Nightmare",
            description=(
                "How to deal with clothes moths.\n"
                "https://gentl.mn/accessories-clothing-fragrance01"
            ),
        )
        status, priority = _classify_transcript_priority(item, GAZETTE_CHANNEL)
        assert (status, priority) == ("none", "none")

    # ------------------------------------------------------------------ Edge cases
    def test_tier2_channel_always_high(self):
        channel = {"quality_tier": "tier_2", "category": "unknown", "title": "Some Channel"}
        item = _make_item(title="random video", description="")
        status, priority = _classify_transcript_priority(item, channel)
        assert (status, priority) == ("needed", "high")

    def test_unrated_non_fragrance_not_queued(self):
        channel = {"quality_tier": "unrated", "category": "unknown", "title": "Cooking Tips"}
        item = _make_item(title="Pasta recipe", description="Boil pasta for 10 minutes.")
        status, priority = _classify_transcript_priority(item, channel)
        assert (status, priority) == ("none", "none")

    def test_unrated_with_fragrance_terms_queued(self):
        channel = {"quality_tier": "unrated", "category": "unknown", "title": "Lifestyle"}
        item = _make_item(title="Top 10 perfume dupes for 2026", description="")
        status, priority = _classify_transcript_priority(item, channel)
        assert (status, priority) == ("needed", "high")
