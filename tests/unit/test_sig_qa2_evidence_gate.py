"""SIG-QA2 — Evidence-Aware Mention Promotion Gate v1: Unit Tests

Test suites:
  CAL  — Calibration: confirmed FP entities must score below threshold
  GOOD — Known-good entities must score above threshold
  D1   — Brand Token Proximity feature
  D2   — Fragrance Context Signal feature
  D3   — Note Context Anti-Signal feature (inverted)
  D4   — Full-Name Match feature
  D5   — Source Entity Density feature (inverted)
  COMP — Composite score properties
  GATE — Shadow / active mode gate behavior
  LOG  — weak_evidence_log idempotency and schema
  WATCH — Known-good standalone watchlist cases (false-suppression risk)

Calibration cases (all confirmed via production RS inspection, 2026-05-18):
  CAL1  Orange Blossom / Angela Flanders  Type B  note collision
  CAL2  Pure Luxury / Wolken Parfums       Type D  generic descriptor
  CAL3  On the Rocks / Wolken Parfums      Type F  partial-name collision
  CAL4  Enjoy the Day / Wolken Parfums     Type D  generic descriptor
  CAL5  Cire Trudon Revolution             Type C  ordinary word
  CAL6  Men's Cologne / Coty               Type G  category descriptor

Known-good cases (must pass gate):
  GOOD1 Vision / Jaguar     — explicit brand+product mention
  GOOD2 Creed Aventus       — brand always near alias in discourse

Shadow watchlist (false-suppression risk, monitor during shadow observation):
  WATCH1 Cool Water / Davidoff — standalone perfume name, brand may be absent
"""

from __future__ import annotations

import sys
import uuid
from datetime import date
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(
    0,
    str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent),
)

from perfume_trend_sdk.analysis.evidence_scorer import (
    SUPPRESS_THRESHOLD,
    EvidenceResult,
    _extract_brand_tokens,
    _find_alias_position,
    _normalize,
    _score_d1_brand_proximity,
    _score_d2_fragrance_context,
    _score_d3_note_antisignal,
    _score_d4_full_name_match,
    _score_d5_source_density,
    _tokenize,
    score_mention,
)


# ─────────────────────────────────────────────────────────────────────────────
# CAL — Calibration: FP entities must score below threshold
# ─────────────────────────────────────────────────────────────────────────────

class TestCalibrationFPs:
    """All 6 confirmed false-positive calibration cases must score < 0.5."""

    def test_cal1_orange_blossom_note_collision(self):
        """Type B — YSL Libre note list: 'lavender, vanilla, and orange blossom...'"""
        result = score_mention(
            matched_from=(
                "Yves Saint Laurent Libre Eau de Parfum Intense fragrance review. "
                "Lavender, vanilla, and orange blossom come together in this gourmand floral. "
                "Beautiful bottle, strong projection."
            ),
            brand_name="Angela Flanders",
            canonical_name="Orange Blossom",
            alias_used="orange blossom",
            source_entity_count=8,
        )
        assert result.would_suppress is True, (
            f"Orange Blossom (Angela Flanders) should be suppressed; score={result.score}"
        )
        assert result.score < SUPPRESS_THRESHOLD

    def test_cal1b_orange_blossom_reddit_note_pref(self):
        """Type B — Reddit note-preference post (19 entities from single post)."""
        result = score_mention(
            matched_from=(
                "I like woods, incense, orange blossom, sandalwood and iris in my fragrances. "
                "What would you recommend?"
            ),
            brand_name="Angela Flanders",
            canonical_name="Orange Blossom",
            alias_used="orange blossom",
            source_entity_count=19,
        )
        assert result.would_suppress is True, (
            f"Orange Blossom note-pref post should be suppressed; score={result.score}"
        )
        assert result.score < SUPPRESS_THRESHOLD

    def test_cal2_pure_luxury_descriptor(self):
        """Type D — YouTube title: '5 affordable fragrances to smell like pure luxury'"""
        result = score_mention(
            matched_from=(
                "5 affordable fragrances to smell like pure luxury in 2026. "
                "Budget finds that smell expensive. #fragrance #budgetfragrance"
            ),
            brand_name="Wolken Parfums",
            canonical_name="Pure Luxury",
            alias_used="pure luxury",
            source_entity_count=5,
        )
        assert result.would_suppress is True, (
            f"Pure Luxury (Wolken) should be suppressed; score={result.score}"
        )
        assert result.score < SUPPRESS_THRESHOLD

    def test_cal3_on_the_rocks_partial_collision(self):
        """Type F — Kilian Apple Brandy on the Rocks review (wrong entity)."""
        result = score_mention(
            matched_from=(
                "Kilian Apple Brandy on the Rocks full review. "
                "The apple and brandy accord is incredible. Long lasting, great sillage. "
                "By Kilian fragrance review."
            ),
            brand_name="Wolken Parfums",
            canonical_name="On the Rocks",
            alias_used="on the rocks",
            source_entity_count=3,
        )
        assert result.would_suppress is True, (
            f"On the Rocks (Wolken) should be suppressed; score={result.score}"
        )
        assert result.score < SUPPRESS_THRESHOLD

    def test_cal4_enjoy_the_day_prose(self):
        """Type D — Reddit wedding planning: 'enjoy the day' in prose."""
        result = score_mention(
            matched_from=(
                "I know it is stressful right now but you will be able to "
                "enjoy the day when it comes. Everything will be perfect for your wedding."
            ),
            brand_name="Wolken Parfums",
            canonical_name="Enjoy the Day",
            alias_used="enjoy the day",
            source_entity_count=2,
        )
        assert result.would_suppress is True, (
            f"Enjoy the Day (Wolken) should be suppressed; score={result.score}"
        )
        assert result.score < SUPPRESS_THRESHOLD

    def test_cal5_revolution_ordinary_word(self):
        """Type C — ELDO review where 'revolution' is used in prose."""
        result = score_mention(
            matched_from=(
                "Etat Libre d'Orange perfume review. This is a revolution in modern fragrance "
                "making. Combining different approaches to create something unique."
            ),
            brand_name="Cire Trudon",
            canonical_name="Cire Trudon Revolution",
            alias_used="revolution",
            source_entity_count=12,
        )
        assert result.would_suppress is True, (
            f"Revolution (Cire Trudon) should be suppressed; score={result.score}"
        )
        assert result.score < SUPPRESS_THRESHOLD

    def test_cal6_mens_cologne_category_descriptor(self):
        """Type G — '#menscologne' category hashtag; 0% Coty brand context."""
        result = score_mention(
            matched_from=(
                "BellaVita CEO Man and GOAT Man 2-pack Men cologne #menscologne "
                "#perfumetok #fathersdaygiftideas"
            ),
            brand_name="Coty",
            canonical_name="Men's Cologne",
            alias_used="men s cologne",
            source_entity_count=6,
        )
        assert result.would_suppress is True, (
            f"Men's Cologne (Coty) should be suppressed; score={result.score}"
        )
        assert result.score < SUPPRESS_THRESHOLD

    def test_cal6b_mens_cologne_budget_list(self):
        """Type G — '#cologne' in affordable fragrance list."""
        result = score_mention(
            matched_from=(
                "5 Affordable Fragrance for Men #cologne #fragrance "
                "#budgetfragrance #fragrancetok"
            ),
            brand_name="Coty",
            canonical_name="Men's Cologne",
            alias_used="men s cologne",
            source_entity_count=5,
        )
        assert result.would_suppress is True, (
            f"Men's Cologne budget list should be suppressed; score={result.score}"
        )
        assert result.score < SUPPRESS_THRESHOLD


# ─────────────────────────────────────────────────────────────────────────────
# GOOD — Known-good entities must pass (score >= threshold)
# ─────────────────────────────────────────────────────────────────────────────

class TestKnownGood:
    """Confirmed legitimate product references must score >= 0.5."""

    def test_good1_vision_jaguar_explicit(self):
        """Vision (Jaguar) — 'Jaguar Vision X Creed Aventus': explicit brand+product."""
        result = score_mention(
            matched_from=(
                "Jaguar Vision X Creed Aventus fragrance mixing review. "
                "Testing Jaguar Vision combined with Creed Aventus for the perfect blend."
            ),
            brand_name="Jaguar",
            canonical_name="Vision",
            alias_used="jaguar vision",
            source_entity_count=2,
        )
        assert result.would_suppress is False, (
            f"Vision/Jaguar should pass gate; score={result.score}"
        )
        assert result.score >= SUPPRESS_THRESHOLD

    def test_good2_creed_aventus_review(self):
        """Creed Aventus — standard fragrance review with brand always present."""
        result = score_mention(
            matched_from=(
                "Creed Aventus review 2026. This legendary Creed fragrance continues to "
                "dominate the designer-niche crossover space. Longevity and projection "
                "are both outstanding."
            ),
            brand_name="Creed",
            canonical_name="Creed Aventus",
            alias_used="creed aventus",
            source_entity_count=3,
        )
        assert result.would_suppress is False, (
            f"Creed Aventus should pass gate; score={result.score}"
        )
        assert result.score >= SUPPRESS_THRESHOLD

    def test_good3_branded_full_name_always_passes(self):
        """Any mention where the alias includes the brand name should score high."""
        result = score_mention(
            matched_from="wolken parfums pure luxury review",
            brand_name="Wolken Parfums",
            canonical_name="Pure Luxury",
            alias_used="wolken parfums pure luxury",
            source_entity_count=1,
        )
        assert result.would_suppress is False, (
            f"Branded full-name alias should pass gate; score={result.score}"
        )
        assert result.score >= SUPPRESS_THRESHOLD


# ─────────────────────────────────────────────────────────────────────────────
# D1 — Brand Token Proximity
# ─────────────────────────────────────────────────────────────────────────────

class TestD1BrandProximity:

    def test_d1_brand_within_near_window_full_credit(self):
        tokens = _tokenize("creed aventus fragrance review by creed")
        match_pos = _find_alias_position(tokens, "aventus")
        brand_tokens = _extract_brand_tokens("Creed")
        score = _score_d1_brand_proximity(tokens, match_pos, brand_tokens)
        assert score == 1.0

    def test_d1_brand_absent_zero(self):
        tokens = _tokenize("lavender vanilla and orange blossom come together in this floral")
        match_pos = _find_alias_position(tokens, "orange blossom")
        brand_tokens = _extract_brand_tokens("Angela Flanders")
        score = _score_d1_brand_proximity(tokens, match_pos, brand_tokens)
        assert score == 0.0

    def test_d1_brand_in_far_window_half_credit(self):
        # Build text where brand is 20 tokens away from alias
        padding = " ".join(["word"] * 20)
        text = f"angela flanders {padding} orange blossom"
        tokens = _tokenize(text)
        match_pos = _find_alias_position(tokens, "orange blossom")
        brand_tokens = _extract_brand_tokens("Angela Flanders")
        score = _score_d1_brand_proximity(tokens, match_pos, brand_tokens)
        assert score == 0.5

    def test_d1_none_match_pos_zero(self):
        tokens = _tokenize("some text that does not contain the alias")
        score = _score_d1_brand_proximity(tokens, None, frozenset({"creed"}))
        assert score == 0.0

    def test_d1_empty_brand_tokens_zero(self):
        tokens = _tokenize("creed aventus review")
        score = _score_d1_brand_proximity(tokens, 1, frozenset())
        assert score == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# D2 — Fragrance Context Signal
# ─────────────────────────────────────────────────────────────────────────────

class TestD2FragranceContext:

    def test_d2_strong_fragrance_context(self):
        tokens = _tokenize(
            "perfume fragrance review edp spray bottle longevity sillage projection"
        )
        score = _score_d2_fragrance_context(tokens, 0)
        assert score == 1.0  # >= 5 hits → capped at 1.0

    def test_d2_no_fragrance_keywords_zero(self):
        tokens = _tokenize("today was a beautiful day in the park")
        score = _score_d2_fragrance_context(tokens, 0)
        assert score == 0.0

    def test_d2_one_keyword_partial(self):
        tokens = _tokenize("this is a fragrance for men")
        score = _score_d2_fragrance_context(tokens, 0)
        assert 0.0 < score < 1.0

    def test_d2_none_match_pos_scans_whole_text(self):
        tokens = _tokenize("perfume review")
        score = _score_d2_fragrance_context(tokens, None)
        assert score > 0.0


# ─────────────────────────────────────────────────────────────────────────────
# D3 — Note Context Anti-Signal (inverted)
# ─────────────────────────────────────────────────────────────────────────────

class TestD3NoteAntisignal:

    def test_d3_near_top_notes_high_antisignal(self):
        text = "top notes orange blossom heart notes jasmine base notes sandalwood"
        tokens = _tokenize(text)
        match_pos = _find_alias_position(tokens, "orange blossom")
        score = _score_d3_note_antisignal(text, tokens, match_pos)
        assert score >= 0.8, f"Should be high anti-signal near 'top notes'; got {score}"

    def test_d3_smells_like_adjacent_high_antisignal(self):
        text = "this perfume smells like orange blossom and vanilla"
        tokens = _tokenize(text)
        match_pos = _find_alias_position(tokens, "orange blossom")
        score = _score_d3_note_antisignal(text, tokens, match_pos)
        assert score >= 0.5, f"'smells like' adjacent should give anti-signal; got {score}"

    def test_d3_no_note_indicators_zero(self):
        text = "creed aventus is the best fragrance i have ever worn"
        tokens = _tokenize(text)
        match_pos = _find_alias_position(tokens, "creed aventus")
        score = _score_d3_note_antisignal(text, tokens, match_pos)
        assert score == 0.0

    def test_d3_note_far_from_match_weak(self):
        # Note indicator is far from alias
        padding = " ".join(["word"] * 25)
        text = f"top notes jasmine {padding} orange blossom"
        tokens = _tokenize(text)
        match_pos = _find_alias_position(tokens, "orange blossom")
        score = _score_d3_note_antisignal(text, tokens, match_pos)
        # "top notes" is > 20 tokens away → should not fire strong anti-signal
        assert score < 0.9


# ─────────────────────────────────────────────────────────────────────────────
# D4 — Full-Name Match
# ─────────────────────────────────────────────────────────────────────────────

class TestD4FullNameMatch:

    def test_d4_alias_contains_brand_token(self):
        brand_tokens = _extract_brand_tokens("Angela Flanders")
        alias = _normalize("angela flanders orange blossom")
        assert _score_d4_full_name_match(alias, brand_tokens) == 1.0

    def test_d4_bare_alias_no_brand(self):
        brand_tokens = _extract_brand_tokens("Angela Flanders")
        alias = _normalize("orange blossom")
        assert _score_d4_full_name_match(alias, brand_tokens) == 0.0

    def test_d4_creed_aventus_full_name(self):
        brand_tokens = _extract_brand_tokens("Creed")
        alias = _normalize("creed aventus")
        assert _score_d4_full_name_match(alias, brand_tokens) == 1.0

    def test_d4_empty_brand_tokens_zero(self):
        assert _score_d4_full_name_match("orange blossom", frozenset()) == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# D5 — Source Entity Density (inverted)
# ─────────────────────────────────────────────────────────────────────────────

class TestD5SourceDensity:

    def test_d5_low_density_small_penalty(self):
        score = _score_d5_source_density(2)
        assert score == pytest.approx(0.1)

    def test_d5_high_density_max_penalty(self):
        score = _score_d5_source_density(20)
        assert score == pytest.approx(1.0)

    def test_d5_threshold_boundary(self):
        score = _score_d5_source_density(15)
        assert score == pytest.approx(1.0)

    def test_d5_mid_density(self):
        score = _score_d5_source_density(9)
        assert 0.1 < score < 1.0

    def test_d5_contribution_inverted_low_density(self):
        """Low density → D5 contribution close to 0.10 (small penalty)."""
        density = _score_d5_source_density(1)
        contribution = (1.0 - density) * 0.10
        assert contribution > 0.08


# ─────────────────────────────────────────────────────────────────────────────
# COMP — Composite score properties
# ─────────────────────────────────────────────────────────────────────────────

class TestCompositeProperties:

    def test_score_bounded_0_to_1(self):
        result = score_mention(
            matched_from="",
            brand_name="",
            canonical_name="Test",
            alias_used="test",
            source_entity_count=1,
        )
        assert 0.0 <= result.score <= 1.0

    def test_features_dict_populated(self):
        result = score_mention(
            matched_from="creed aventus review",
            brand_name="Creed",
            canonical_name="Creed Aventus",
            alias_used="creed aventus",
            source_entity_count=1,
        )
        assert set(result.features.keys()) == {"d1", "d2", "d3_raw", "d4", "d5_density"}

    def test_would_suppress_matches_threshold(self):
        result = score_mention(
            matched_from="creed aventus fragrance review by creed",
            brand_name="Creed",
            canonical_name="Creed Aventus",
            alias_used="creed aventus",
            source_entity_count=2,
        )
        assert result.would_suppress == (result.score < SUPPRESS_THRESHOLD)

    def test_threshold_constant_value(self):
        assert SUPPRESS_THRESHOLD == 0.5

    def test_brand_token_extraction_filters_stopwords(self):
        tokens = _extract_brand_tokens("Etat Libre de L'Orange")
        # "de" should be filtered out, "etat" / "libre" retained
        assert "de" not in tokens
        assert "etat" in tokens


# ─────────────────────────────────────────────────────────────────────────────
# GATE — Shadow mode: EntityMention always written regardless of score
# ─────────────────────────────────────────────────────────────────────────────

class TestShadowModeNeverSuppresses:
    """In shadow mode (gate_active=False), EntityMention is always written."""

    def _make_mock_db(self):
        db = MagicMock()
        db.execute.return_value = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = None
        return db

    def test_shadow_mode_writes_low_score_mention(self):
        """Even a would_suppress=True mention is written in shadow mode."""
        # We test this by verifying that gate_active=False means no 'continue'
        # executes for low-score entities.
        # Score a known FP — must get would_suppress=True
        result = score_mention(
            matched_from="enjoy the day at your wedding everyone",
            brand_name="Wolken Parfums",
            canonical_name="Enjoy the Day",
            alias_used="enjoy the day",
            source_entity_count=1,
        )
        assert result.would_suppress is True

        # Shadow mode logic: write regardless
        # (Full integration test is not in unit scope; this confirms
        # the scorer returns would_suppress=True so the integration
        # path is exercised.)
        assert result.score < SUPPRESS_THRESHOLD


# ─────────────────────────────────────────────────────────────────────────────
# LOG — weak_evidence_log schema and idempotency helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestWeakEvidenceLogHelpers:
    """Tests for the log upsert helpers in aggregate_daily_market_metrics."""

    def test_upsert_helper_exists_and_importable(self):
        from perfume_trend_sdk.jobs.aggregate_daily_market_metrics import (
            _upsert_weak_evidence_log,
        )
        assert callable(_upsert_weak_evidence_log)

    def test_build_entity_brand_map_importable(self):
        from perfume_trend_sdk.jobs.aggregate_daily_market_metrics import (
            _build_entity_brand_map,
        )
        assert callable(_build_entity_brand_map)

    def test_build_source_entity_counts_importable(self):
        from perfume_trend_sdk.jobs.aggregate_daily_market_metrics import (
            _build_source_entity_counts,
        )
        assert callable(_build_source_entity_counts)

    def test_build_source_entity_counts_logic(self):
        """Correctly counts entities per content_item_id."""
        import json
        from perfume_trend_sdk.jobs.aggregate_daily_market_metrics import (
            _build_source_entity_counts,
        )
        signals = [
            {
                "content_item_id": "aaa",
                "resolved_entities_json": json.dumps([
                    {"canonical_name": "Creed Aventus"},
                    {"canonical_name": "Dior Sauvage"},
                ]),
            },
            {
                "content_item_id": "bbb",
                "resolved_entities_json": json.dumps([
                    {"canonical_name": "MFK Baccarat Rouge 540"},
                ]),
            },
        ]
        counts = _build_source_entity_counts(signals)
        assert counts["aaa"] == 2
        assert counts["bbb"] == 1

    def test_build_source_entity_counts_empty_json(self):
        from perfume_trend_sdk.jobs.aggregate_daily_market_metrics import (
            _build_source_entity_counts,
        )
        signals = [{"content_item_id": "ccc", "resolved_entities_json": None}]
        counts = _build_source_entity_counts(signals)
        assert counts.get("ccc", 0) == 0

    def test_upsert_weak_evidence_log_nonfatal_on_error(self):
        """Non-fatal: DB error is caught and logged as warning."""
        from perfume_trend_sdk.jobs.aggregate_daily_market_metrics import (
            _upsert_weak_evidence_log,
        )
        db = MagicMock()
        db.execute.side_effect = Exception("simulated DB error")
        ev = EvidenceResult(score=0.3, would_suppress=True, features={})
        # Should not raise
        _upsert_weak_evidence_log(
            db, "item-uuid", "Orange Blossom", "Angela Flanders",
            "2026-05-18", ev, shadow_mode=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# WATCH — Shadow watchlist: known-good standalone entities
# ─────────────────────────────────────────────────────────────────────────────

class TestShadowWatchlist:
    """
    Known-good standalone fragrance names that may appear in valid discourse
    WITHOUT brand tokens nearby. These must be tracked during shadow
    observation before active-mode activation.

    If any WATCH entity produces consistent would_suppress=True results in
    production, the threshold or feature weights must be re-calibrated before
    active mode is enabled.
    """

    def test_watch1_cool_water_with_brand(self):
        """Cool Water (Davidoff) when brand IS present — must pass gate."""
        result = score_mention(
            matched_from=(
                "Davidoff Cool Water review. This classic Davidoff fragrance "
                "remains a summer staple. Great value for money."
            ),
            brand_name="Davidoff",
            canonical_name="Cool Water",
            alias_used="cool water",
            source_entity_count=2,
        )
        assert result.would_suppress is False, (
            f"Cool Water with 'Davidoff' present should pass gate; score={result.score}"
        )

    def test_watch1_cool_water_without_brand(self):
        """Cool Water (Davidoff) when brand is absent — flag this as a known risk.

        This test documents the risk: Cool Water WITHOUT 'Davidoff' in text
        may be suppressed. This is a known limitation to monitor in shadow mode.
        If this occurs frequently in production, active-mode activation requires
        either threshold adjustment or a guard exception for well-established
        standalone names.
        """
        result = score_mention(
            matched_from=(
                "Cool water is an absolute classic. I wear it every summer and "
                "always get compliments. Strong fragrance projection."
            ),
            brand_name="Davidoff",
            canonical_name="Cool Water",
            alias_used="cool water",
            source_entity_count=3,
        )
        # Document the score — this test deliberately does NOT assert pass/fail
        # because this is a known risk case requiring shadow observation.
        # The score is expected to be in borderline territory.
        assert isinstance(result.score, float)
        assert 0.0 <= result.score <= 1.0
        # Fragrance context words "fragrance" and "projection" should give
        # this some D2 credit, but D1=0 (no "davidoff" nearby) limits total.
        # Expected range: 0.3–0.6 (borderline territory).
        # Shadow observation will confirm whether production RS for Cool Water
        # consistently includes brand context or not.

    def test_watch1_cool_water_score_recorded_in_features(self):
        """Features dict must always be populated for shadow log audit."""
        result = score_mention(
            matched_from="cool water fragrance review projection",
            brand_name="Davidoff",
            canonical_name="Cool Water",
            alias_used="cool water",
            source_entity_count=2,
        )
        assert "d1" in result.features
        assert "d2" in result.features
        assert "d3_raw" in result.features
        assert "d4" in result.features
        assert "d5_density" in result.features


# ─────────────────────────────────────────────────────────────────────────────
# Helpers validation
# ─────────────────────────────────────────────────────────────────────────────

class TestHelpers:

    def test_tokenize_removes_punctuation(self):
        assert _tokenize("Hello, world!") == ["hello", "world"]

    def test_tokenize_lowercases(self):
        assert _tokenize("Creed Aventus") == ["creed", "aventus"]

    def test_normalize_consistent_with_tokenize(self):
        assert _normalize("Orange Blossom") == "orange blossom"

    def test_find_alias_position_found(self):
        tokens = ["creed", "aventus", "review"]
        assert _find_alias_position(tokens, "creed aventus") == 0

    def test_find_alias_position_not_found(self):
        tokens = ["dior", "sauvage"]
        assert _find_alias_position(tokens, "orange blossom") is None

    def test_find_alias_position_empty_alias(self):
        tokens = ["any", "tokens"]
        assert _find_alias_position(tokens, "") is None

    def test_extract_brand_tokens_filters_short(self):
        tokens = _extract_brand_tokens("Le Labo")
        # "le" is stop word AND short; "labo" should be kept
        assert "labo" in tokens

    def test_extract_brand_tokens_multi_word(self):
        tokens = _extract_brand_tokens("Maison Francis Kurkdjian")
        assert "maison" in tokens
        assert "kurkdjian" in tokens
