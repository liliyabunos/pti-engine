from __future__ import annotations

"""
Phase I3 — Trend State Layer

Pure-function classification of an entity's trend direction on a given day.
Inputs: current day's market metrics + previous day's score for context.

States (priority order — first match wins):
  breakout   — strong growth from a solid base, or explicit breakout/spike signal
  declining  — was notable, now collapsing
  rising     — positive growth building, score above noise floor
  peak       — high score but growth slowing/flat at the top
  emerging   — first appearance or tiny score with upward pressure
  stable     — active entity with no strong directional signal
  None       — carry-forward row (no activity today) or score == 0

Thresholds are deliberately conservative to avoid false positives.
They are also defined here as module-level constants so they can be adjusted
in tests or future tuning without touching the computation logic.
"""

from typing import Optional

# ---------------------------------------------------------------------------
# Thresholds (tune here, not in compute_trend_state)
# ---------------------------------------------------------------------------

BREAKOUT_MIN_SCORE: float = 15.0
BREAKOUT_MIN_GROWTH: float = 0.35   # 35% growth vs prior day
BREAKOUT_MIN_MENTIONS: float = 2.0

DECLINING_PREV_MIN: float = 10.0    # prev score must have been "notable"
DECLINING_SCORE_RATIO: float = 0.50 # current < 50% of previous
DECLINING_GROWTH_THRESHOLD: float = -0.30  # OR growth < -30% from notable base
DECLINING_PREV_NOTABLE: float = 5.0        # "notable base" for growth-only declining

RISING_MIN_GROWTH: float = 0.15     # 15% growth
RISING_MIN_SCORE: float = 5.0
RISING_MOMENTUM_THRESHOLD: float = 0.30  # positive momentum signal

PEAK_MIN_SCORE: float = 20.0
PEAK_GROWTH_LO: float = -0.05       # growth between -5% and +10% = slowing plateau
PEAK_GROWTH_HI: float = 0.10

EMERGING_MAX_SCORE: float = 10.0    # low score entity with any positive signal


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def compute_trend_state(
    score: float,
    prev_score: Optional[float],
    growth_rate: Optional[float],
    momentum: Optional[float],
    acceleration: Optional[float],
    mention_count: float,
    latest_signal_type: Optional[str] = None,
) -> Optional[str]:
    """Classify an entity's trend direction for a single day.

    Args:
        score:              composite_market_score for the current day.
        prev_score:         composite_market_score for the most-recent prior
                            day with real activity (mention_count > 0). None
                            if this is the entity's first ever appearance.
        growth_rate:        day-over-day growth relative to prev_score.
        momentum:           multi-day momentum indicator (aggregator output).
        acceleration:       change in momentum (aggregator output).
        mention_count:      number of real content mentions today (0 = carry-forward).
        latest_signal_type: signal_type of the most recently detected signal
                            for this entity ('breakout', 'acceleration_spike', …).

    Returns:
        One of: 'breakout', 'rising', 'peak', 'stable', 'declining', 'emerging',
        or None (carry-forward / zero-score row).
    """
    # Carry-forward rows — no activity today, no trend state.
    if mention_count == 0:
        return None

    # Normalise to zero when absent.
    g = growth_rate if growth_rate is not None else 0.0
    m = momentum if momentum is not None else 0.0
    prev = prev_score if prev_score is not None else 0.0

    # ── 1. BREAKOUT ────────────────────────────────────────────────────────
    # Strong growth from a solid base, backed by multiple mentions.
    if (
        score >= BREAKOUT_MIN_SCORE
        and g >= BREAKOUT_MIN_GROWTH
        and mention_count >= BREAKOUT_MIN_MENTIONS
    ):
        return "breakout"
    # Explicit signal confirmation (signal detection already passed thresholds).
    if latest_signal_type in ("breakout", "acceleration_spike") and score >= 10.0:
        return "breakout"

    # ── 2. DECLINING ───────────────────────────────────────────────────────
    # Entity had meaningful activity and has now lost more than half of it.
    if prev >= DECLINING_PREV_MIN and score < prev * DECLINING_SCORE_RATIO:
        return "declining"
    # OR: growth rate is sharply negative from a notable base.
    if g < DECLINING_GROWTH_THRESHOLD and prev >= DECLINING_PREV_NOTABLE:
        return "declining"

    # ── 3. RISING ──────────────────────────────────────────────────────────
    # Clear positive momentum above noise floor.
    if g >= RISING_MIN_GROWTH and score >= RISING_MIN_SCORE and mention_count >= 1:
        return "rising"
    # Positive sustained momentum even without a single-day spike.
    if m >= RISING_MOMENTUM_THRESHOLD and score >= RISING_MIN_SCORE:
        return "rising"

    # ── 4. PEAK ────────────────────────────────────────────────────────────
    # High score but growth has slowed to a plateau — the "top of the wave".
    if score >= PEAK_MIN_SCORE and PEAK_GROWTH_LO <= g <= PEAK_GROWTH_HI:
        return "peak"

    # ── 5. EMERGING ────────────────────────────────────────────────────────
    # First-ever appearance with any real score.
    if prev == 0 and score > 0 and mention_count >= 1:
        return "emerging"
    # Small but growing — early signal worth watching.
    if score < EMERGING_MAX_SCORE and g > 0 and mention_count >= 1:
        return "emerging"

    # ── 6. STABLE ──────────────────────────────────────────────────────────
    # Active entity, but no strong directional signal in either direction.
    if score > 0:
        return "stable"

    # Zero score with activity — shouldn't normally happen, but guard cleanly.
    return None
