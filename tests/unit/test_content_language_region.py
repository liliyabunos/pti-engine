"""Phase 043 — Content Language & Region Propagation v1

Tests for the channel_context → content item language/region derivation logic.

Coverage:
  _resolve_content_language() — module-level helper
  _resolve_content_region()   — module-level helper
  _COUNTRY_TO_REGION          — mapping dict completeness
  SocialContentNormalizer.normalize_youtube_item() — channel_context integration

Boundaries confirmed:
  - No migration (canonical_content_items.region / language already exist)
  - No historical backfill
  - entity_mentions.region deferred
  - TikTok / Reddit normalizers unchanged (scope limited to YouTube channel_poll)
  - Scoring fields unaffected
  - Public-safe views unaffected (region/language not exposed)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from perfume_trend_sdk.normalizers.social_content.normalizer import (
    SocialContentNormalizer,
    _COUNTRY_TO_REGION,
    _resolve_content_language,
    _resolve_content_region,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_raw_youtube_item(video_id: str = "abc123", channel_id: str = "UCtest") -> dict:
    """Minimal raw YouTube item that the normalizer can process."""
    return {
        "search_item": {
            "id": {"videoId": video_id},
            "snippet": {
                "publishedAt": "2026-05-11T10:00:00Z",
                "channelId": channel_id,
                "channelTitle": "Test Channel",
                "title": "Fragrance Review",
                "description": "Great fragrance review.",
            },
        },
        "video_details": {
            "statistics": {"viewCount": "1000", "likeCount": "50", "commentCount": "5"},
        },
    }


# ---------------------------------------------------------------------------
# Tests for _resolve_content_language()
# ---------------------------------------------------------------------------

class TestResolveContentLanguage:

    def test_none_context_returns_none(self):
        """No context provided = not attempted = None (legacy/backward-compat)."""
        result = _resolve_content_language(None)
        assert result is None

    def test_context_with_language_returns_language(self):
        result = _resolve_content_language({"language": "en"})
        assert result == "en"

    def test_context_with_non_english_language(self):
        result = _resolve_content_language({"language": "es"})
        assert result == "es"

    def test_context_with_arabic_language(self):
        result = _resolve_content_language({"language": "ar"})
        assert result == "ar"

    def test_context_with_none_language_returns_unknown(self):
        """Context provided but language is None = attempted, not determinable."""
        result = _resolve_content_language({"language": None})
        assert result == "UNKNOWN"

    def test_empty_context_returns_unknown(self):
        """Context provided but no language key = attempted, not determinable."""
        result = _resolve_content_language({})
        assert result == "UNKNOWN"

    def test_context_with_empty_string_language_returns_unknown(self):
        result = _resolve_content_language({"language": ""})
        assert result == "UNKNOWN"

    def test_context_with_whitespace_language_returns_unknown(self):
        result = _resolve_content_language({"language": "  "})
        assert result == "UNKNOWN"

    def test_language_is_stripped(self):
        """Language string should be stripped of surrounding whitespace."""
        result = _resolve_content_language({"language": "  de  "})
        assert result == "de"


# ---------------------------------------------------------------------------
# Tests for _resolve_content_region()
# ---------------------------------------------------------------------------

class TestResolveContentRegion:

    def test_none_context_returns_unknown(self):
        """No context = UNKNOWN (not 'US' — we don't assume US)."""
        result = _resolve_content_region(None)
        assert result == "UNKNOWN"

    def test_source_region_takes_priority(self):
        """source_region (set by operator via Phase 042) takes priority over country."""
        result = _resolve_content_region({
            "source_region": "UK_IRELAND",
            "country": "US",  # would map to US_CANADA, but source_region wins
        })
        assert result == "UK_IRELAND"

    def test_source_region_used_when_country_absent(self):
        result = _resolve_content_region({"source_region": "MIDDLE_EAST_GCC"})
        assert result == "MIDDLE_EAST_GCC"

    def test_country_us_maps_to_us_canada(self):
        result = _resolve_content_region({"source_region": None, "country": "US"})
        assert result == "US_CANADA"

    def test_country_ca_maps_to_us_canada(self):
        result = _resolve_content_region({"source_region": None, "country": "CA"})
        assert result == "US_CANADA"

    def test_country_gb_maps_to_uk_ireland(self):
        result = _resolve_content_region({"source_region": None, "country": "GB"})
        assert result == "UK_IRELAND"

    def test_country_de_maps_to_eu_dach(self):
        result = _resolve_content_region({"source_region": None, "country": "DE"})
        assert result == "EU_DACH"

    def test_country_fr_maps_to_eu_francophone(self):
        result = _resolve_content_region({"source_region": None, "country": "FR"})
        assert result == "EU_FRANCOPHONE"

    def test_country_br_maps_to_brazil(self):
        result = _resolve_content_region({"source_region": None, "country": "BR"})
        assert result == "BRAZIL"

    def test_country_ae_maps_to_middle_east_gcc(self):
        result = _resolve_content_region({"source_region": None, "country": "AE"})
        assert result == "MIDDLE_EAST_GCC"

    def test_country_in_maps_to_south_asia(self):
        result = _resolve_content_region({"source_region": None, "country": "IN"})
        assert result == "SOUTH_ASIA"

    def test_country_jp_maps_to_east_asia(self):
        result = _resolve_content_region({"source_region": None, "country": "JP"})
        assert result == "EAST_ASIA"

    def test_country_sg_maps_to_southeast_asia(self):
        result = _resolve_content_region({"source_region": None, "country": "SG"})
        assert result == "SOUTHEAST_ASIA"

    def test_unknown_country_returns_unknown(self):
        """Country code not in the map → UNKNOWN, not a crash."""
        result = _resolve_content_region({"source_region": None, "country": "ZZ"})
        assert result == "UNKNOWN"

    def test_none_country_and_none_source_region_returns_unknown(self):
        result = _resolve_content_region({"source_region": None, "country": None})
        assert result == "UNKNOWN"

    def test_empty_context_returns_unknown(self):
        result = _resolve_content_region({})
        assert result == "UNKNOWN"

    def test_country_is_case_insensitive(self):
        """Country codes from the API may be lowercase in some edge cases."""
        result = _resolve_content_region({"source_region": None, "country": "us"})
        assert result == "US_CANADA"

    def test_country_is_stripped(self):
        result = _resolve_content_region({"source_region": None, "country": "  GB  "})
        assert result == "UK_IRELAND"

    def test_empty_source_region_falls_through_to_country(self):
        """Empty string source_region should not be used — fall through to country."""
        result = _resolve_content_region({"source_region": "", "country": "DE"})
        assert result == "EU_DACH"


# ---------------------------------------------------------------------------
# Tests for _COUNTRY_TO_REGION coverage
# ---------------------------------------------------------------------------

class TestCountryToRegionMap:

    def test_key_fragrance_market_countries_present(self):
        """Critical fragrance market countries must be in the map."""
        required = {
            "US", "CA",          # US/Canada
            "GB", "IE",          # UK/Ireland
            "DE", "AT", "CH",    # DACH
            "FR",                # Francophone
            "IT", "ES",          # EU South
            "BR",                # Brazil
            "AE", "SA",          # GCC
            "IN", "PK",          # South Asia
            "JP", "KR",          # East Asia
            "ID", "SG",          # SE Asia
        }
        missing = required - set(_COUNTRY_TO_REGION.keys())
        assert not missing, f"Missing country codes: {missing}"

    def test_all_values_are_valid_region_buckets(self):
        valid_buckets = {
            "US_CANADA", "UK_IRELAND", "EU_DACH", "EU_FRANCOPHONE", "EU_SOUTH",
            "LATAM", "BRAZIL", "MIDDLE_EAST_GCC", "SOUTH_ASIA",
            "EAST_ASIA", "SOUTHEAST_ASIA",
        }
        invalid = {v for v in _COUNTRY_TO_REGION.values() if v not in valid_buckets}
        assert not invalid, f"Invalid region bucket values: {invalid}"


# ---------------------------------------------------------------------------
# Tests for normalize_youtube_item() with channel_context
# ---------------------------------------------------------------------------

class TestNormalizeYoutubeItemWithContext:
    normalizer = SocialContentNormalizer()

    def test_no_context_language_is_none(self):
        """No channel_context → language=None (not attempted, backward compat)."""
        item = self.normalizer.normalize_youtube_item(
            _make_raw_youtube_item(), raw_payload_ref="ref/test"
        )
        assert item["language"] is None

    def test_no_context_region_is_unknown(self):
        """No channel_context → region='UNKNOWN' (not 'US')."""
        item = self.normalizer.normalize_youtube_item(
            _make_raw_youtube_item(), raw_payload_ref="ref/test"
        )
        assert item["region"] == "UNKNOWN"

    def test_channel_context_language_propagated(self):
        """Channel with language='en' → content language='en'."""
        item = self.normalizer.normalize_youtube_item(
            _make_raw_youtube_item(),
            raw_payload_ref="ref/test",
            channel_context={"language": "en", "country": "US", "source_region": None},
        )
        assert item["language"] == "en"

    def test_channel_context_source_region_propagated(self):
        """Channel with source_region='UK_IRELAND' → content region='UK_IRELAND'."""
        item = self.normalizer.normalize_youtube_item(
            _make_raw_youtube_item(),
            raw_payload_ref="ref/test",
            channel_context={"language": "en", "country": "GB", "source_region": "UK_IRELAND"},
        )
        assert item["region"] == "UK_IRELAND"

    def test_channel_context_country_fallback_when_no_source_region(self):
        """Country='DE', source_region=None → region derived from country map → 'EU_DACH'."""
        item = self.normalizer.normalize_youtube_item(
            _make_raw_youtube_item(),
            raw_payload_ref="ref/test",
            channel_context={"language": "de", "country": "DE", "source_region": None},
        )
        assert item["region"] == "EU_DACH"

    def test_channel_context_no_mapping_falls_to_unknown(self):
        """Country not in map and no source_region → 'UNKNOWN'."""
        item = self.normalizer.normalize_youtube_item(
            _make_raw_youtube_item(),
            raw_payload_ref="ref/test",
            channel_context={"language": None, "country": "XK", "source_region": None},
        )
        assert item["region"] == "UNKNOWN"
        assert item["language"] == "UNKNOWN"

    def test_channel_context_all_none_returns_unknown(self):
        """All fields None in context → language='UNKNOWN', region='UNKNOWN'."""
        item = self.normalizer.normalize_youtube_item(
            _make_raw_youtube_item(),
            raw_payload_ref="ref/test",
            channel_context={"language": None, "country": None, "source_region": None},
        )
        assert item["language"] == "UNKNOWN"
        assert item["region"] == "UNKNOWN"

    def test_arabic_channel_context(self):
        """Arabic channel: language='ar', country='AE', no source_region → correct propagation."""
        item = self.normalizer.normalize_youtube_item(
            _make_raw_youtube_item(),
            raw_payload_ref="ref/test",
            channel_context={"language": "ar", "country": "AE", "source_region": None},
        )
        assert item["language"] == "ar"
        assert item["region"] == "MIDDLE_EAST_GCC"

    def test_spanish_latam_channel_context(self):
        """Spanish/LATAM channel: language='es', country='MX' → correct propagation."""
        item = self.normalizer.normalize_youtube_item(
            _make_raw_youtube_item(),
            raw_payload_ref="ref/test",
            channel_context={"language": "es", "country": "MX", "source_region": None},
        )
        assert item["language"] == "es"
        assert item["region"] == "LATAM"

    def test_channel_context_with_operator_approved_global(self):
        """Operator set source_region='GLOBAL_ENGLISH' → that value is used directly."""
        item = self.normalizer.normalize_youtube_item(
            _make_raw_youtube_item(),
            raw_payload_ref="ref/test",
            channel_context={
                "language": "en",
                "country": "US",
                "source_region": "GLOBAL_ENGLISH",
            },
        )
        assert item["region"] == "GLOBAL_ENGLISH"

    def test_scoring_fields_unaffected_by_channel_context(self):
        """channel_context must not alter engagement, source_url, or source fields."""
        raw = _make_raw_youtube_item(video_id="vid999", channel_id="UCtest999")
        item = self.normalizer.normalize_youtube_item(
            raw,
            raw_payload_ref="ref/scoring",
            channel_context={"language": "en", "country": "US", "source_region": "US_CANADA"},
        )
        # Core identity / scoring-relevant fields must be unchanged
        assert item["source_platform"] == "youtube"
        assert item["external_content_id"] == "vid999"
        assert item["source_account_id"] == "UCtest999"
        assert item["engagement"]["views"] == 1000  # from test raw data viewCount
        assert item["normalizer_version"] == "1.0"

    def test_backward_compat_existing_callers_without_context(self):
        """Callers that do not pass channel_context still work (default=None)."""
        item = self.normalizer.normalize_youtube_item(
            _make_raw_youtube_item(), raw_payload_ref="ref/compat"
        )
        # Must not raise; region is UNKNOWN (not "US"), language is None
        assert item["region"] == "UNKNOWN"
        assert item["language"] is None
        assert item["source_platform"] == "youtube"


# ---------------------------------------------------------------------------
# Tests confirming TikTok and Reddit normalizers are unaffected by Phase 043
# ---------------------------------------------------------------------------

class TestOtherNormalizersUnaffected:
    """Phase 043 touches only normalize_youtube_item(). TikTok and Reddit
    normalizers are out of scope and must remain unchanged."""

    normalizer = SocialContentNormalizer()

    def test_tiktok_item_region_unchanged(self):
        """normalize_tiktok_item must still return region='US' (Phase 043 out of scope)."""
        raw_tiktok = {
            "id": "tt123",
            "author": {"uniqueId": "testhandle"},
            "desc": "Fragrance haul",
            "createTime": 1715000000,
            "stats": {"playCount": 1000, "diggCount": 50, "commentCount": 5, "shareCount": 2},
            "video": {"duration": 30},
        }
        item = self.normalizer.normalize_tiktok_item(
            raw_tiktok, raw_payload_ref="ref/tiktok"
        )
        assert item["region"] == "US"

    def test_reddit_item_region_unchanged(self):
        """normalize_reddit_item must still return region='US' (Phase 043 out of scope)."""
        raw_reddit = {
            "id": "r123",
            "author": "testuser",
            "title": "Best fragrances for spring",
            "selftext": "My favorites are...",
            "url": "https://reddit.com/r/fragrance/comments/r123",
            "permalink": "/r/fragrance/comments/r123",
            "subreddit": "fragrance",
            "score": 42,
            "num_comments": 8,
            "created_utc": 1715000000,
        }
        item = self.normalizer.normalize_reddit_item(
            raw_reddit, raw_payload_ref="ref/reddit"
        )
        assert item["region"] == "US"
