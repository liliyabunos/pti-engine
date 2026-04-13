from __future__ import annotations

import json
from pathlib import Path

import pytest

from perfume_trend_sdk.connectors.tiktok_watchlist.parser import TikTokParser

FIXTURE_PATH = Path(__file__).parent.parent.parent / "fixtures" / "tiktok_post_raw.json"


def load_fixture() -> dict:
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def raw_post() -> dict:
    return load_fixture()


@pytest.fixture
def parser() -> TikTokParser:
    return TikTokParser()


def test_parse_external_content_id(parser: TikTokParser, raw_post: dict) -> None:
    result = parser.parse(raw_post)
    assert result["external_content_id"] == "7234567890123456789"


def test_parse_source_url(parser: TikTokParser, raw_post: dict) -> None:
    result = parser.parse(raw_post)
    url = result["source_url"]
    assert "perfume_lover_usa" in url
    assert "7234567890123456789" in url
    assert url.startswith("https://www.tiktok.com/@")


def test_parse_caption(parser: TikTokParser, raw_post: dict) -> None:
    result = parser.parse(raw_post)
    assert "Delina" in result["caption"]
    assert "Parfums de Marly" in result["caption"]


def test_parse_hashtags(parser: TikTokParser, raw_post: dict) -> None:
    result = parser.parse(raw_post)
    hashtags = result["hashtags"]
    assert isinstance(hashtags, list)
    assert len(hashtags) > 0
    assert "perfume" in hashtags


def test_parse_published_at(parser: TikTokParser, raw_post: dict) -> None:
    result = parser.parse(raw_post)
    published_at = result["published_at"]
    assert isinstance(published_at, str)
    assert len(published_at) > 0
    # Basic ISO 8601 check — should contain a T separator
    assert "T" in published_at


def test_parse_engagement(parser: TikTokParser, raw_post: dict) -> None:
    result = parser.parse(raw_post)
    assert isinstance(result["views"], int)
    assert isinstance(result["likes"], int)
    assert isinstance(result["comments"], int)
    assert isinstance(result["shares"], int)
    assert result["views"] == 124300
    assert result["likes"] == 8900
    assert result["comments"] == 342
    assert result["shares"] == 1200


def test_parse_followers(parser: TikTokParser, raw_post: dict) -> None:
    result = parser.parse(raw_post)
    assert isinstance(result["followers"], int)
    assert result["followers"] == 48200


def test_parse_tolerates_empty_dict(parser: TikTokParser) -> None:
    """Parser must not raise on an empty dict — all fields default to safe values."""
    result = parser.parse({})
    assert isinstance(result, dict)
    assert result["external_content_id"] == ""
    assert result["source_url"] == ""
    assert result["caption"] == ""
    assert result["hashtags"] == []
    assert result["views"] == 0
    assert result["likes"] == 0
    assert result["comments"] == 0
    assert result["shares"] == 0
    assert result["followers"] == 0
    assert result["duration_seconds"] == 0
