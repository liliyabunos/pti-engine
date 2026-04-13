from __future__ import annotations

"""
Breakout Signal Detector — Market Engine v1

Detects signal events from daily snapshot data without touching
any existing pipeline code.

Signal types:
  new_entry          — entity appears for the first time with mentions
  breakout           — composite_market_score surges vs previous day
  acceleration_spike — momentum accelerated sharply
  reversal           — entity was rising, now dropping
"""

from typing import Any, Dict, List, Optional

DEFAULT_THRESHOLDS: Dict[str, float] = {
    # Breakout
    "breakout_min_score": 15.0,          # lowered from 20 — real YouTube data produces lower scores
    "breakout_min_mentions": 2.0,        # require ≥2 mentions to avoid single-video spikes
    "breakout_growth_pct": 0.35,         # lowered from 0.50 — 35% growth qualifies

    # Acceleration spike
    "acceleration_spike_threshold": 1.5, # momentum ratio ≥ 1.5 (unchanged)

    # Reversal — noise-suppression additions
    "reversal_drop_pct": 0.40,           # score dropped ≥40% from prev day (unchanged)
    "reversal_prev_min_score": 15.0,     # prev day must have been meaningful (unchanged)
    "reversal_min_mentions": 2.0,        # suppress reversals on single-mention days
    "reversal_max_score_ratio": 4.0,     # if prev_score > 4× cur_score, likely a data-source
                                         # transition (synthetic→real), not a real reversal
}


class BreakoutDetector:
    """Detect market signal events from daily entity snapshots."""

    def __init__(
        self, thresholds: Optional[Dict[str, float]] = None
    ) -> None:
        self.thresholds = thresholds or DEFAULT_THRESHOLDS

    def detect(
        self,
        current: Dict[str, Any],
        previous: Optional[Dict[str, Any]],
        detected_at: str,
    ) -> List[Dict[str, Any]]:
        """Return list of signal dicts for this entity on detected_at.

        Args:
            current:     Today's snapshot dict (entity_daily_snapshots row).
            previous:    Yesterday's snapshot dict, or None if first run.
            detected_at: ISO date string (YYYY-MM-DD) for the signal record.

        Returns:
            List of signal dicts: {entity_id, signal_type, detected_at,
                                   score, details}
        """
        signals: List[Dict[str, Any]] = []
        entity_id = current["entity_id"]
        cur_score = float(current.get("composite_market_score", 0))
        cur_momentum = float(current.get("momentum", 0))
        cur_acceleration = float(current.get("acceleration", 0))
        cur_mentions = float(current.get("mention_count", 0))

        t = self.thresholds

        # ── new_entry ────────────────────────────────────────────────
        if previous is None and cur_mentions > 0:
            signals.append(self._signal(
                entity_id, "new_entry", detected_at, cur_score,
                {"mention_count": cur_mentions},
            ))
            return signals

        if previous is None:
            return signals

        prev_score = float(previous.get("composite_market_score", 0))
        prev_momentum = float(previous.get("momentum", 0))

        # ── breakout ─────────────────────────────────────────────────
        # Requires: score above floor AND enough mentions AND meaningful growth.
        if (
            cur_score >= t["breakout_min_score"]
            and cur_mentions >= t["breakout_min_mentions"]
        ):
            if prev_score == 0:
                growth_ratio = float("inf")
            else:
                growth_ratio = (cur_score - prev_score) / prev_score
            if growth_ratio >= t["breakout_growth_pct"]:
                signals.append(self._signal(
                    entity_id, "breakout", detected_at, cur_score,
                    {"prev_score": prev_score, "growth_pct": round(growth_ratio * 100, 1)},
                ))

        # ── acceleration_spike ───────────────────────────────────────
        if cur_momentum >= t["acceleration_spike_threshold"]:
            signals.append(self._signal(
                entity_id, "acceleration_spike", detected_at, cur_score,
                {"momentum": round(cur_momentum, 3), "acceleration": round(cur_acceleration, 3)},
            ))

        # ── reversal ─────────────────────────────────────────────────
        # Noise-suppression rules (applied before standard threshold):
        #   1. cur_mentions < min → not enough data to confirm a real reversal.
        #   2. prev_score / cur_score > max_ratio → the gap is so extreme it likely
        #      reflects a data-source transition (e.g. synthetic→real YouTube),
        #      not genuine market movement.
        if prev_score >= t["reversal_prev_min_score"] and prev_score > 0:
            drop_ratio = (prev_score - cur_score) / prev_score
            if drop_ratio >= t["reversal_drop_pct"]:
                score_ratio = prev_score / max(cur_score, 0.01)
                if (
                    cur_mentions >= t["reversal_min_mentions"]
                    and score_ratio <= t["reversal_max_score_ratio"]
                ):
                    signals.append(self._signal(
                        entity_id, "reversal", detected_at, cur_score,
                        {
                            "prev_score": prev_score,
                            "drop_pct": round(drop_ratio * 100, 1),
                            "prev_momentum": round(prev_momentum, 3),
                        },
                    ))

        return signals

    def detect_batch(
        self,
        snapshots: List[Dict[str, Any]],
        prev_snapshots: Dict[str, Dict[str, Any]],
        detected_at: str,
    ) -> List[Dict[str, Any]]:
        """Detect signals for a batch of entity snapshots.

        Args:
            snapshots:     List of current-day snapshot dicts.
            prev_snapshots: Map of entity_id → previous snapshot dict.
            detected_at:   ISO date string for the signal records.

        Returns:
            Flat list of all detected signal dicts.
        """
        all_signals: List[Dict[str, Any]] = []
        for snap in snapshots:
            eid = snap["entity_id"]
            prev = prev_snapshots.get(eid)
            all_signals.extend(self.detect(snap, prev, detected_at))
        return all_signals

    # ------------------------------------------------------------------

    @staticmethod
    def _signal(
        entity_id: Any,  # uuid.UUID in practice; kept generic for pure-logic portability
        signal_type: str,
        detected_at: str,
        strength: float,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "entity_id": entity_id,
            "signal_type": signal_type,
            "detected_at": detected_at,
            "strength": round(strength, 4),
            "metadata": metadata,
        }
