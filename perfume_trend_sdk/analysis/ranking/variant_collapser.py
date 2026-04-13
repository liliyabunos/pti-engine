from __future__ import annotations

"""
Ranking Integrity — Variant Collapser + Flood Suppressor

Two leaderboard integrity problems are corrected at *serving time* — never by
mutating stored entity records or timeseries rows.

Problem 1 — Concentration/form variant duplicates
  "Chanel Bleu de Chanel" and "Chanel Bleu de Chanel Eau de Parfum" are the
  same perfume.  Without collapsing they occupy two leaderboard rows, inflating
  their brand's apparent share and burying other perfumes.

  Solution: group entities whose canonical_names share the same stripped base
  (after removing trailing concentration/form terms), elect a primary entity
  (the base-form record when it exists, otherwise the highest-scoring variant),
  and sum mention_count / engagement across variants into a single row.
  All original entity_ids are preserved in the collapsed row for traceability.

Problem 2 — Single-post collection flood
  A Reddit post listing 12 Le Labo scents resolves to 12 separate entities, each
  with mention_count=1 and unique_authors=1. They flood the leaderboard at the
  same score as perfumes that were mentioned by 2 independent authors.

  Solution: apply a dampening factor to composite_market_score when
  unique_authors < FLOOD_AUTHOR_FLOOR. The effective_rank_score (not the stored
  value) is used for sorting. The original composite_market_score is preserved
  for display and entity-level analytics.

Both corrections are composable — a variant group that also has unique_authors=1
receives both corrections (mentions merged, score dampened).
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from perfume_trend_sdk.utils.alias_generator import normalize_text, strip_concentration

# ---------------------------------------------------------------------------
# Flood-suppression constants
# ---------------------------------------------------------------------------

#: Multiplicative factor applied to composite_market_score when unique_authors
#: is below FLOOD_AUTHOR_FLOOR. A value of 0.6 gives single-author entities
#: 60% of their nominal score, enough to stay visible in signals/screener
#: but not enough to dominate the leaderboard.
FLOOD_DAMPENING_FACTOR: float = 0.6

#: Minimum unique authors required for full undampened leaderboard ranking.
FLOOD_AUTHOR_FLOOR: int = 2


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------

@dataclass
class CollapsedRow:
    """A leaderboard-ready row that may represent multiple variant entities."""

    # Primary entity identity (base form without concentration suffix)
    entity_id: str
    entity_type: str
    ticker: str
    canonical_name: str
    brand_name: Optional[str]

    # Merged metrics (summed or max as described per field)
    mention_count: float          # sum across variants
    unique_authors: int           # max across variants (sets not available at serving time)
    engagement_sum: float         # sum across variants
    composite_market_score: float # max across variants (conservative, avoids score inflation)
    growth_rate: Optional[float]  # max (best growth signal among variants)
    momentum: Optional[float]     # max
    acceleration: Optional[float] # max abs value
    volatility: Optional[float]   # max
    confidence_avg: Optional[float]  # max

    # Leaderboard ranking fields
    effective_rank_score: float   # composite_market_score * flood_dampening(unique_authors)
    is_flood_dampened: bool       # True when unique_authors < FLOOD_AUTHOR_FLOOR

    # Latest signal (best strength across all variants)
    latest_signal: Optional[str] = None
    latest_signal_strength: Optional[float] = None

    # Traceability — collapsed-away variants
    variant_names: List[str] = field(default_factory=list)
    variant_entity_ids: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Variant grouping key
# ---------------------------------------------------------------------------

def variant_group_key(canonical_name: str) -> str:
    """Return the normalized base name used to group concentration variants.

    Examples:
      "Chanel Bleu de Chanel Eau de Parfum"  → "chanel bleu de chanel"
      "Chanel Bleu de Chanel"                → "chanel bleu de chanel"
      "Initio Oud for Greatness Eau de Parfum" → "initio oud for greatness"
      "Initio Oud for Greatness"             → "initio oud for greatness"
      "Dior Sauvage Elixir"                  → "dior sauvage elixir"   (Elixir is NOT stripped)
    """
    stripped = strip_concentration(canonical_name)
    return normalize_text(stripped)


# ---------------------------------------------------------------------------
# Flood dampening
# ---------------------------------------------------------------------------

def compute_effective_rank_score(
    composite_market_score: float,
    unique_authors: int,
) -> Tuple[float, bool]:
    """Return (effective_rank_score, is_flood_dampened).

    Dampening applies when unique_authors < FLOOD_AUTHOR_FLOOR (i.e. ≤ 1).
    Entities with no recorded author (unique_authors == 0) are also dampened.
    """
    if unique_authors < FLOOD_AUTHOR_FLOOR:
        return round(composite_market_score * FLOOD_DAMPENING_FACTOR, 4), True
    return composite_market_score, False


# ---------------------------------------------------------------------------
# Primary election
# ---------------------------------------------------------------------------

def _elect_primary(
    members: List[Tuple[Any, Any]],
    group_key: str,
) -> Tuple[Any, Any]:
    """Choose the primary (EntityMarket, EntityTimeSeriesDaily) for a group.

    Priority:
      1. Entity whose normalize_text(canonical_name) exactly equals group_key
         — this is the base form without the concentration suffix.
      2. Highest composite_market_score among remaining candidates.
    """
    for em, snap in members:
        if normalize_text(em.canonical_name) == group_key:
            return em, snap
    return max(members, key=lambda t: (t[1].composite_market_score or 0.0))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _slug(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", name.lower().strip())
    return re.sub(r"[\s_]+", "-", s).strip("-")


def collapse_and_rank(
    rows: List[Tuple[Any, Any]],
    latest_signal_map: Optional[Dict] = None,
    brand_name_map: Optional[Dict] = None,
) -> List[CollapsedRow]:
    """Collapse concentration variants, apply flood dampening, and rank.

    Args:
        rows:              (EntityMarket, EntityTimeSeriesDaily|None) pairs —
                           output of fetch_latest_rows(). Pairs with snap=None
                           are excluded (no timeseries data → not rankable).
        latest_signal_map: {entity UUID → (signal_type, strength)} — output of
                           fetch_latest_signal_map(). Used to propagate the
                           best signal from any variant to the collapsed row.
        brand_name_map:    {slug → brand_name} — output of fetch_brand_name_map().
                           Used as a fallback when entity_market.brand_name is
                           absent.

    Returns:
        List of CollapsedRow sorted by effective_rank_score DESC.
        Entities with no snapshot are omitted.
    """
    latest_signal_map = latest_signal_map or {}
    brand_name_map = brand_name_map or {}

    # ── Phase 1: group by variant key ──────────────────────────────────────
    groups: Dict[str, List[Tuple[Any, Any]]] = {}
    for em, snap in rows:
        if snap is None:
            continue
        key = variant_group_key(em.canonical_name)
        groups.setdefault(key, []).append((em, snap))

    # ── Phase 2: merge each group into one CollapsedRow ────────────────────
    collapsed: List[CollapsedRow] = []

    for key, members in groups.items():
        primary_em, primary_snap = _elect_primary(members, key)

        # Merged metrics
        total_mentions = sum((s.mention_count or 0.0) for _, s in members)
        total_engagement = sum((s.engagement_sum or 0.0) for _, s in members)
        max_authors = max((s.unique_authors or 0) for _, s in members)
        best_score = max((s.composite_market_score or 0.0) for _, s in members)
        best_growth = max((s.growth_rate or 0.0) for _, s in members)
        best_momentum = max((s.momentum or 0.0) for _, s in members)
        best_accel = max((abs(s.acceleration) if s.acceleration else 0.0) for _, s in members)
        best_volatility = max((s.volatility or 0.0) for _, s in members)
        best_confidence = max((s.confidence_avg or 0.0) for _, s in members) or None

        # Traceability
        variant_names = [
            em.canonical_name
            for em, _ in members
            if em.entity_id != primary_em.entity_id
        ]
        variant_eids = [
            em.entity_id
            for em, _ in members
            if em.entity_id != primary_em.entity_id
        ]

        # Flood dampening on merged unique_authors
        eff_score, dampened = compute_effective_rank_score(best_score, max_authors)

        # Brand name: primary entity's brand_name or map fallback
        brand_name = primary_em.brand_name
        if not brand_name:
            brand_name = brand_name_map.get(_slug(primary_em.entity_id))

        # Latest signal: best strength from any variant UUID
        sig_type: Optional[str] = None
        sig_strength: Optional[float] = None
        for em, _ in members:
            sig = latest_signal_map.get(em.id)
            if sig:
                if sig_strength is None or (sig[1] or 0.0) > (sig_strength or 0.0):
                    sig_type = sig[0]
                    sig_strength = sig[1]

        collapsed.append(CollapsedRow(
            entity_id=primary_em.entity_id,
            entity_type=primary_em.entity_type,
            ticker=primary_em.ticker,
            canonical_name=primary_em.canonical_name,
            brand_name=brand_name,
            mention_count=total_mentions,
            unique_authors=max_authors,
            engagement_sum=total_engagement,
            composite_market_score=best_score,
            growth_rate=best_growth,
            momentum=best_momentum,
            acceleration=best_accel,
            volatility=best_volatility,
            confidence_avg=best_confidence,
            effective_rank_score=eff_score,
            is_flood_dampened=dampened,
            latest_signal=sig_type,
            latest_signal_strength=sig_strength,
            variant_names=variant_names,
            variant_entity_ids=variant_eids,
        ))

    # ── Phase 3: sort by effective_rank_score DESC ─────────────────────────
    collapsed.sort(key=lambda r: r.effective_rank_score, reverse=True)
    return collapsed
