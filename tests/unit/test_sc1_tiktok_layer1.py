"""SC1.1 — TikTok Layer 1 unit tests.

Covers:
  - mention_weight_override=0.0 derived items do not increment mention_count
  - mention_weight_override=0.7 direct items use override weight (not platform default)
  - mention_weight_override=None items use platform default (0.9)
  - No double-count: same content item id counted only once per entity
  - TikTok URL extractor: correct URL detection, dedup, snippet generation
  - normalize_tiktok_derived_item: correct fields on output
  - oEmbed proxy: host validation, safe fallback
  - Source submissions: TikTok video+context vs video-only classification
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_item(
    item_id: str,
    platform: str,
    published: str,
    mention_weight_override: Any = None,
    engagement: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return {
        "id": item_id,
        "source_platform": platform,
        "published_at": published,
        "engagement_json": None,
        "media_metadata_json": None,
        "engagement": engagement or {},
        "media_metadata": {},
        "mention_weight_override": mention_weight_override,
        "source_account_handle": "testcreator",
        "content_type": "video",
        "text_content": None,
        "title": None,
    }


def _make_signal(content_item_id: str, entity_name: str) -> Dict[str, Any]:
    import json
    return {
        "content_item_id": content_item_id,
        "resolved_entities_json": json.dumps([
            {"entity_type": "perfume", "canonical_name": entity_name, "confidence": 1.0}
        ]),
    }


# ---------------------------------------------------------------------------
# Aggregator: mention_weight_override behaviour
# ---------------------------------------------------------------------------

class TestAggregatorMentionWeightOverride:
    """Test that mention_weight_override is respected in DailyAggregator."""

    def _run(self, items, signals, date="2026-05-07"):
        import json
        from perfume_trend_sdk.analysis.market_signals.aggregator import DailyAggregator

        # Patch items so they look like they came from _load_content_items
        for item in items:
            item["published_at"] = date  # match target_date
            if "engagement_json" not in item or item["engagement_json"] is None:
                item["engagement_json"] = json.dumps(item.get("engagement", {}))
            if "media_metadata_json" not in item or item["media_metadata_json"] is None:
                item["media_metadata_json"] = json.dumps(item.get("media_metadata", {}))

        agg = DailyAggregator()
        return agg.aggregate_from_data(items, signals, date)

    def test_derived_tiktok_zero_weight_no_mention_count(self):
        """mention_weight_override=0.0 → mention_count stays 0."""
        items = [_make_item("tok1", "tiktok", "2026-05-07", mention_weight_override=0.0)]
        signals = [_make_signal("tok1", "Baccarat Rouge 540")]
        snapshots = self._run(items, signals)
        assert len(snapshots) == 1
        snap = snapshots[0]
        assert snap["mention_count"] == 0.0, (
            f"Derived TikTok (weight=0.0) must not increment mention_count, got {snap['mention_count']}"
        )

    def test_direct_tiktok_07_weight_uses_override(self):
        """mention_weight_override=0.7 → mention_count is 0.7, not platform default 0.9."""
        items = [_make_item("tok2", "tiktok", "2026-05-07", mention_weight_override=0.7)]
        signals = [_make_signal("tok2", "Creed Aventus")]
        snapshots = self._run(items, signals)
        assert len(snapshots) == 1
        snap = snapshots[0]
        assert abs(snap["mention_count"] - 0.7) < 1e-9, (
            f"Expected mention_count=0.7 (weight override), got {snap['mention_count']}"
        )

    def test_tiktok_no_override_uses_platform_default_09(self):
        """mention_weight_override=None → uses platform default 0.9 (not old 1.3)."""
        items = [_make_item("tok3", "tiktok", "2026-05-07", mention_weight_override=None)]
        signals = [_make_signal("tok3", "Dior Sauvage")]
        snapshots = self._run(items, signals)
        assert len(snapshots) == 1
        snap = snapshots[0]
        assert abs(snap["mention_count"] - 0.9) < 1e-9, (
            f"Expected TikTok platform weight 0.9, got {snap['mention_count']}"
        )

    def test_no_double_count_same_content_item(self):
        """Same content item id resolving two entities counts once per entity."""
        item = _make_item("tok4", "tiktok", "2026-05-07", mention_weight_override=0.9)
        import json
        item["engagement_json"] = json.dumps({})
        item["media_metadata_json"] = json.dumps({})
        signals = [
            {
                "content_item_id": "tok4",
                "resolved_entities_json": json.dumps([
                    {"entity_type": "perfume", "canonical_name": "Baccarat Rouge 540", "confidence": 1.0},
                    {"entity_type": "perfume", "canonical_name": "Baccarat Rouge 540", "confidence": 1.0},
                ]),
            }
        ]
        from perfume_trend_sdk.analysis.market_signals.aggregator import DailyAggregator
        item["published_at"] = "2026-05-07"
        agg = DailyAggregator()
        snapshots = agg.aggregate_from_data([item], signals, "2026-05-07")
        assert len(snapshots) == 1
        snap = snapshots[0]
        assert abs(snap["mention_count"] - 0.9) < 1e-9, (
            f"Same entity from same item must be counted once; got {snap['mention_count']}"
        )

    def test_derived_tiktok_still_adds_to_engagement(self):
        """mention_weight_override=0.0: engagement_sum should still accumulate."""
        import json
        item = _make_item(
            "tok5", "tiktok", "2026-05-07",
            mention_weight_override=0.0,
            engagement={"views": 100000, "likes": 5000},
        )
        item["engagement_json"] = json.dumps(item["engagement"])
        item["media_metadata_json"] = json.dumps({})
        signals = [_make_signal("tok5", "Tom Ford Tobacco Vanille")]
        from perfume_trend_sdk.analysis.market_signals.aggregator import DailyAggregator
        agg = DailyAggregator()
        snapshots = agg.aggregate_from_data([item], signals, "2026-05-07")
        snap = snapshots[0]
        assert snap["mention_count"] == 0.0
        # engagement_sum should be > 0 (views cap + likes×3)
        assert snap["engagement_sum"] > 0, "Derived TikTok engagement must still accumulate"


# ---------------------------------------------------------------------------
# Platform weight constant
# ---------------------------------------------------------------------------

def test_tiktok_platform_weight_is_09():
    """TikTok platform weight must be 0.9 (SC1.1 correction 1: was 1.3)."""
    from perfume_trend_sdk.analysis.market_signals.aggregator import _PLATFORM_WEIGHTS
    assert _PLATFORM_WEIGHTS["tiktok"] == 0.9, (
        f"TikTok weight must be 0.9, got {_PLATFORM_WEIGHTS['tiktok']}"
    )


# ---------------------------------------------------------------------------
# TikTok URL extractor
# ---------------------------------------------------------------------------

class TestTikTokUrlExtractor:
    """Unit tests for perfume_trend_sdk.ingest.tiktok_url_extractor."""

    def _find(self, text):
        from perfume_trend_sdk.ingest.tiktok_url_extractor import find_tiktok_video_urls
        return find_tiktok_video_urls(text)

    def test_detects_standard_video_url(self):
        matches = self._find(
            "Check this TikTok https://www.tiktok.com/@perfumeguy/video/7123456789012345678"
        )
        assert len(matches) == 1
        assert matches[0].video_id == "7123456789012345678"
        assert matches[0].handle == "perfumeguy"

    def test_deduplicates_same_video_id(self):
        text = (
            "https://www.tiktok.com/@perfumeguy/video/7123456789012345678 and "
            "https://www.tiktok.com/@perfumeguy/video/7123456789012345678"
        )
        matches = self._find(text)
        assert len(matches) == 1

    def test_ignores_channel_profile_urls(self):
        matches = self._find("https://www.tiktok.com/@perfumeguy")
        assert len(matches) == 0

    def test_ignores_non_tiktok_urls(self):
        matches = self._find("https://www.youtube.com/watch?v=abc123")
        assert len(matches) == 0

    def test_empty_text(self):
        from perfume_trend_sdk.ingest.tiktok_url_extractor import find_tiktok_video_urls
        assert find_tiktok_video_urls("") == []
        assert find_tiktok_video_urls(None) == []  # type: ignore

    def test_multiple_distinct_urls(self):
        text = (
            "First video https://www.tiktok.com/@user1/video/1111111111111111111 "
            "Second video https://www.tiktok.com/@user2/video/2222222222222222222"
        )
        matches = self._find(text)
        assert len(matches) == 2

    def test_context_snippet_captured(self):
        text = "I love this perfume https://www.tiktok.com/@fragdude/video/9999999999999999999 so much!"
        matches = self._find(text)
        assert len(matches) == 1
        assert "I love this perfume" in matches[0].context_snippet
        assert len(matches[0].context_snippet) <= 200

    def test_extract_tiktok_video_urls_returns_items(self):
        from perfume_trend_sdk.ingest.tiktok_url_extractor import extract_tiktok_video_urls
        items = extract_tiktok_video_urls(
            parent_id="yt_abc123",
            text="Check https://www.tiktok.com/@fragdude/video/7000000000000000001",
        )
        assert len(items) == 1
        item = items[0]
        assert item["mention_weight_override"] == 0.0
        assert item["tiktok_layer"] == 1
        assert item["referencing_source_id"] == "yt_abc123"
        assert item["source_platform"] == "tiktok"
        assert item["id"] == "7000000000000000001"


# ---------------------------------------------------------------------------
# normalize_tiktok_derived_item
# ---------------------------------------------------------------------------

class TestNormalizeTikTokDerivedItem:
    def _normalizer(self):
        from perfume_trend_sdk.normalizers.social_content.normalizer import SocialContentNormalizer
        return SocialContentNormalizer()

    def test_valid_url_produces_item(self):
        n = self._normalizer()
        item = n.normalize_tiktok_derived_item(
            tiktok_url="https://www.tiktok.com/@handle/video/1234567890123456789",
            referencing_source_id="yt_parent",
            referencing_context="some context about a perfume",
        )
        assert item is not None
        assert item["id"] == "1234567890123456789"
        assert item["mention_weight_override"] == 0.0
        assert item["tiktok_layer"] == 1
        assert item["referencing_source_id"] == "yt_parent"
        assert item["referencing_context"] == "some context about a perfume"
        assert item["source_platform"] == "tiktok"

    def test_invalid_url_returns_none(self):
        n = self._normalizer()
        result = n.normalize_tiktok_derived_item(
            tiktok_url="https://www.tiktok.com/@handle",
            referencing_source_id="yt_parent",
            referencing_context="",
        )
        assert result is None

    def test_context_capped_at_200_chars(self):
        n = self._normalizer()
        long_context = "x" * 500
        item = n.normalize_tiktok_derived_item(
            tiktok_url="https://www.tiktok.com/@h/video/1234567890123456789",
            referencing_source_id="yt_p",
            referencing_context=long_context,
        )
        assert len(item["referencing_context"]) <= 200

    def test_normalize_tiktok_item_accepts_layer_fields(self):
        n = self._normalizer()
        raw = {
            "id": "9999999999999999999",
            "author": {"uniqueId": "creator", "id": "uid1", "followerCount": 1000},
            "desc": "Baccarat Rouge 540 review #br540",
            "createTime": 1714000000,
            "stats": {"playCount": 5000, "diggCount": 200, "commentCount": 10, "shareCount": 5},
            "video": {"duration": 30},
        }
        item = n.normalize_tiktok_item(
            raw,
            "ref_payload",
            tiktok_layer=1,
            mention_weight_override=0.7,
            referencing_source_id=None,
            referencing_context=None,
        )
        assert item["tiktok_layer"] == 1
        assert item["mention_weight_override"] == 0.7
        assert item["referencing_source_id"] is None


# ---------------------------------------------------------------------------
# oEmbed proxy: host validation
# ---------------------------------------------------------------------------

class TestOEmbedValidation:
    def _validate(self, url):
        from perfume_trend_sdk.api.routes.tiktok_oembed import _validate_tiktok_url
        return _validate_tiktok_url(url)

    def test_valid_tiktok_video_url(self):
        assert self._validate(
            "https://www.tiktok.com/@fragdude/video/7123456789012345678"
        ) is True

    def test_rejects_non_tiktok_host(self):
        assert self._validate("https://evil.com/@fragdude/video/1234567890123456789") is False

    def test_rejects_channel_profile_url(self):
        assert self._validate("https://www.tiktok.com/@fragdude") is False

    def test_rejects_youtube_url(self):
        assert self._validate("https://www.youtube.com/watch?v=abc") is False

    def test_rejects_empty_string(self):
        assert self._validate("") is False

    def test_rejects_tiktok_search_url(self):
        assert self._validate("https://www.tiktok.com/search?q=perfume") is False

    def test_oembed_returns_safe_fallback_on_bad_url(self):
        from perfume_trend_sdk.api.routes.tiktok_oembed import tiktok_oembed
        result = tiktok_oembed(url="https://evil.com/video/123")
        assert result == {"html": None}

    def test_oembed_returns_safe_fallback_on_network_error(self):
        from perfume_trend_sdk.api.routes.tiktok_oembed import tiktok_oembed
        with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
            result = tiktok_oembed(url="https://www.tiktok.com/@user/video/1234567890123456789")
        assert result == {"html": None}


# ---------------------------------------------------------------------------
# Source submissions: TikTok classification helpers
# ---------------------------------------------------------------------------

class TestSourceSubmissionsTikTokHelpers:
    def test_is_tiktok_video_url_true(self):
        from perfume_trend_sdk.api.routes.source_submissions import _is_tiktok_video_url
        assert _is_tiktok_video_url(
            "https://www.tiktok.com/@creator/video/7000000000000000001"
        ) is True

    def test_is_tiktok_video_url_false_for_profile(self):
        from perfume_trend_sdk.api.routes.source_submissions import _is_tiktok_video_url
        assert _is_tiktok_video_url("https://www.tiktok.com/@creator") is False

    def test_is_tiktok_video_url_false_for_non_tiktok(self):
        from perfume_trend_sdk.api.routes.source_submissions import _is_tiktok_video_url
        assert _is_tiktok_video_url("https://www.youtube.com/watch?v=abc") is False

    def test_detect_platform_returns_tiktok(self):
        from perfume_trend_sdk.api.routes.source_submissions import _detect_platform
        assert _detect_platform("https://www.tiktok.com/@creator/video/123") == "tiktok"

    def test_tiktok_url_type_is_platform_pending(self):
        from perfume_trend_sdk.api.routes.source_submissions import _determine_initial_status
        db = MagicMock()
        status = _determine_initial_status(
            "https://www.tiktok.com/@creator/video/1234567890123456789",
            "tiktok",
            db,
        )
        assert status == "platform_pending"

    def test_tiktok_channel_url_type_is_platform_pending(self):
        from perfume_trend_sdk.api.routes.source_submissions import _determine_initial_status
        db = MagicMock()
        status = _determine_initial_status(
            "https://www.tiktok.com/@creator",
            "tiktok",
            db,
        )
        assert status == "platform_pending"
