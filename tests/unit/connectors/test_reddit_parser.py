from __future__ import annotations

import json
from pathlib import Path

import pytest

from perfume_trend_sdk.connectors.reddit_watchlist.parser import RedditParser

FIXTURE_PATH = Path(__file__).parent.parent.parent / "fixtures" / "reddit_post_raw.json"


@pytest.fixture(scope="module")
def raw_post() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def parsed(raw_post: dict) -> dict:
    return RedditParser().parse(raw_post)


# ------------------------------------------------------------------
# Field extraction
# ------------------------------------------------------------------

def test_parse_external_content_id(parsed: dict) -> None:
    assert parsed["external_content_id"] == "abc123x"


def test_parse_subreddit(parsed: dict) -> None:
    assert parsed["subreddit"] == "fragrance"


def test_parse_title(parsed: dict) -> None:
    assert "Delina" in parsed["title"]
    assert "Parfums de Marly" in parsed["title"]


def test_parse_selftext(parsed: dict) -> None:
    assert "vanilla" in parsed["selftext"]
    assert "Baccarat Rouge 540" in parsed["selftext"]


def test_parse_author(parsed: dict) -> None:
    assert parsed["source_account_handle"] == "fragrance_nerd_us"


def test_parse_source_url_uses_permalink(parsed: dict) -> None:
    assert parsed["source_url"].startswith("https://www.reddit.com")
    assert "fragrance" in parsed["source_url"]
    assert "abc123x" in parsed["source_url"]


def test_parse_published_at_is_iso(parsed: dict) -> None:
    pub = parsed["published_at"]
    assert pub != ""
    assert "T" in pub  # ISO 8601


def test_parse_score(parsed: dict) -> None:
    assert parsed["score"] == 342


def test_parse_num_comments(parsed: dict) -> None:
    assert parsed["num_comments"] == 87


def test_parse_link_flair_text(parsed: dict) -> None:
    assert parsed["link_flair_text"] == "Review"


def test_parse_media_metadata_has_subreddit(parsed: dict) -> None:
    assert parsed["media_metadata"]["subreddit"] == "fragrance"


def test_parse_media_metadata_has_upvote_ratio(parsed: dict) -> None:
    assert parsed["media_metadata"]["upvote_ratio"] == pytest.approx(0.97)


# ------------------------------------------------------------------
# Tolerance for missing fields
# ------------------------------------------------------------------

def test_parse_tolerates_empty_dict() -> None:
    result = RedditParser().parse({})
    assert result["external_content_id"] == ""
    assert result["title"] == ""
    assert result["selftext"] == ""
    assert result["source_account_handle"] is None
    assert result["published_at"] == ""
    assert result["score"] == 0
    assert result["num_comments"] == 0
    assert result["link_flair_text"] is None


def test_parse_tolerates_missing_selftext() -> None:
    result = RedditParser().parse({"id": "z1", "title": "Just a title"})
    assert result["selftext"] == ""
    assert result["title"] == "Just a title"


def test_parse_source_url_from_id_and_subreddit_when_no_permalink() -> None:
    result = RedditParser().parse({"id": "q9w8e7", "subreddit": "fragrance"})
    assert "fragrance" in result["source_url"]
    assert "q9w8e7" in result["source_url"]


def test_parse_source_url_absolute_permalink_unchanged() -> None:
    result = RedditParser().parse({
        "id": "x1",
        "permalink": "https://www.reddit.com/r/fragrance/comments/x1/title/"
    })
    assert result["source_url"] == "https://www.reddit.com/r/fragrance/comments/x1/title/"


def test_parse_invalid_timestamp() -> None:
    result = RedditParser().parse({"id": "x1", "created_utc": "not-a-number"})
    assert result["published_at"] == ""


def test_parse_is_deterministic(raw_post: dict) -> None:
    r1 = RedditParser().parse(raw_post)
    r2 = RedditParser().parse(raw_post)
    assert r1 == r2
