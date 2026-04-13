from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from perfume_trend_sdk.extractors.note_mentions.extractor import NoteExtractor


# Default thresholds for driver detection
_DEFAULT_ENGAGEMENT_THRESHOLD = 0.001   # avg engagement_weight per mention
_DEFAULT_FREQUENCY_THRESHOLD = 3        # mention_count
_DEFAULT_TOP_PERFUMES_N = 10            # how many top perfumes count as "trending"


class NoteMomentumScorer:
    """Compute note-level trend scores from resolved signals and content items.

    Formula:
        note_score = (mention_count × 0.6)
                   + (engagement_weight × 0.3)
                   + (official_note_bonus × 0.1)

    Where:
        engagement_weight = normalized average engagement per mention
            (views × 0.6 + likes × 0.4) / 1_000_000
        official_note_bonus = 1 if note exists in any Fragrantica official notes,
                              else 0

    Each note also receives a `drivers` list explaining WHY it is trending:
        "high engagement"                   — avg engagement exceeds threshold
        "present in top trending perfumes"  — note linked to a top-N perfume
        "high mention frequency"            — mention_count exceeds threshold

    Constraints:
    - No connector calls
    - No canonical entity mutation
    - Stateless — same inputs always produce same output
    """

    name = "note_momentum_scorer"
    version = "1.0"

    def __init__(
        self,
        engagement_threshold: float = _DEFAULT_ENGAGEMENT_THRESHOLD,
        frequency_threshold: int = _DEFAULT_FREQUENCY_THRESHOLD,
        top_perfumes_n: int = _DEFAULT_TOP_PERFUMES_N,
    ) -> None:
        self.engagement_threshold = engagement_threshold
        self.frequency_threshold = frequency_threshold
        self.top_perfumes_n = top_perfumes_n

    def score(
        self,
        *,
        content_items: List[Dict[str, Any]],
        resolved_signals: List[Dict[str, Any]],
        enrichment_registry: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Compute note momentum scores.

        Args:
            content_items: Normalized content items (must have id, text_content, engagement).
            resolved_signals: Stored resolved signals (must have content_item_id,
                              resolved_entities_json).
            enrichment_registry: Optional dict mapping canonical_name → enriched perfume dict.
                                 Used to build the official_notes set for confidence boost.

        Returns:
            Dict mapping note name → {
                note_score, mention_count, engagement_weight,
                official_note_bonus, perfumes, drivers
            }
        """
        extractor = NoteExtractor.from_enrichment_registry(enrichment_registry or {})
        content_map: Dict[str, Dict[str, Any]] = {
            item["id"]: item for item in content_items
        }

        # Build top-perfume set from resolved signals (by raw mention count)
        perfume_counts: Dict[str, int] = {}
        for signal in resolved_signals:
            try:
                entities = json.loads(signal.get("resolved_entities_json") or "[]")
            except (ValueError, TypeError):
                entities = []
            for e in entities:
                if e.get("entity_type") == "perfume" and e.get("canonical_name"):
                    name = e["canonical_name"]
                    perfume_counts[name] = perfume_counts.get(name, 0) + 1

        top_perfume_set = {
            name
            for name, _ in sorted(
                perfume_counts.items(), key=lambda x: x[1], reverse=True
            )[: self.top_perfumes_n]
        }

        # note → accumulator
        stats: Dict[str, Dict[str, Any]] = {}

        for signal in resolved_signals:
            item_id = signal.get("content_item_id", "")
            content_item = content_map.get(item_id, {})
            text = content_item.get("text_content") or ""

            engagement = content_item.get("engagement") or {}
            views = _safe_int(engagement.get("views"))
            likes = _safe_int(engagement.get("likes"))
            item_engagement = (views * 0.6 + likes * 0.4) / 1_000_000

            # Collect perfume names resolved for this content item
            try:
                entities = json.loads(signal.get("resolved_entities_json") or "[]")
            except (ValueError, TypeError):
                entities = []
            perfume_names = [
                e["canonical_name"]
                for e in entities
                if e.get("entity_type") == "perfume" and e.get("canonical_name")
            ]

            note_mentions = extractor.extract(text)
            for nm in note_mentions:
                note = nm["note"]
                bonus = nm["official_note_bonus"]

                if note not in stats:
                    stats[note] = {
                        "mention_count": 0,
                        "total_engagement": 0.0,
                        "official_note_bonus": 0,
                        "perfumes": set(),
                    }

                stats[note]["mention_count"] += 1
                stats[note]["total_engagement"] += item_engagement
                # bonus is sticky: once official, always official
                stats[note]["official_note_bonus"] = max(
                    stats[note]["official_note_bonus"], bonus
                )
                for pname in perfume_names:
                    stats[note]["perfumes"].add(pname)

        return {
            note: _finalize(
                note,
                acc,
                engagement_threshold=self.engagement_threshold,
                frequency_threshold=self.frequency_threshold,
                top_perfume_set=top_perfume_set,
            )
            for note, acc in stats.items()
        }


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _finalize(
    note: str,
    acc: Dict[str, Any],
    *,
    engagement_threshold: float,
    frequency_threshold: int,
    top_perfume_set: set,
) -> Dict[str, Any]:
    mc = acc["mention_count"]
    avg_engagement = acc["total_engagement"] / mc if mc > 0 else 0.0
    ob = acc["official_note_bonus"]
    note_score = round((mc * 0.6) + (avg_engagement * 0.3) + (ob * 0.1), 4)
    perfumes = sorted(acc["perfumes"])

    drivers: List[str] = []
    if avg_engagement > engagement_threshold:
        drivers.append("high engagement")
    if any(p in top_perfume_set for p in perfumes):
        drivers.append("present in top trending perfumes")
    if mc >= frequency_threshold:
        drivers.append("high mention frequency")

    return {
        "note_score": note_score,
        "mention_count": mc,
        "engagement_weight": round(avg_engagement, 6),
        "official_note_bonus": ob,
        "perfumes": perfumes,
        "drivers": drivers,
    }


def compute_trend_delta(
    current: Dict[str, Dict[str, Any]],
    previous: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Compute period-over-period delta for each note.

    Args:
        current: Note scores for the current period (from NoteMomentumScorer.score).
        previous: Note scores for the previous period (loaded via load_note_scores).

    Returns:
        Dict mapping note → {current_score, previous_score, delta, direction}.
        Covers all notes that appear in either period.
        Notes absent in current have current_score = 0 (they disappeared).
        Notes absent in previous have previous_score = 0 (they are new).
    """
    all_notes = set(current.keys()) | set(previous.keys())
    result: Dict[str, Dict[str, Any]] = {}
    for note in all_notes:
        cur = current.get(note, {}).get("note_score", 0.0)
        prev = previous.get(note, {}).get("note_score", 0.0)
        delta = round(cur - prev, 4)
        result[note] = {
            "current_score": round(cur, 4),
            "previous_score": round(prev, 4),
            "delta": delta,
            "direction": direction_from_delta(delta),
        }
    return result


def direction_from_delta(delta: float) -> str:
    """Real trend direction based on period-over-period delta.

    "up"   delta > 0
    "down" delta < 0
    "flat" delta == 0
    """
    if abs(delta) < 0.05:
        return "flat"
    if delta > 0:
        return "up"
    return "down"


def save_note_scores(scores: Dict[str, Dict[str, Any]], path: str) -> None:
    """Persist note scores to JSON so the next run can compute deltas.

    Call this at the end of each pipeline run after scoring.
    Serialises `perfumes` list (sets are not JSON-serialisable).
    """
    serialisable = {
        note: {**data, "perfumes": list(data.get("perfumes", []))}
        for note, data in scores.items()
    }
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(serialisable, ensure_ascii=False, indent=2), encoding="utf-8")


def load_note_scores(path: str) -> Dict[str, Dict[str, Any]]:
    """Load previously saved note scores.

    Returns an empty dict if the file does not exist yet (first run).
    """
    src = Path(path)
    if not src.exists():
        return {}
    try:
        return json.loads(src.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def build_note_results(
    scores: Dict[str, Dict[str, Any]],
    deltas: Optional[Dict[str, Dict[str, Any]]] = None,
    *,
    n: int = 10,
) -> List[Dict[str, Any]]:
    """Return top-N notes as clean unified dicts.

    Each dict contains exactly:
        note      — note name (str)
        score     — current note_score (float)
        direction — "up" / "down" / "flat" from delta when available,
                    else heuristic from absolute score ("↑"/"→"/"↓")
        drivers   — list of driver strings (may be empty)

    Args:
        scores: Output of NoteMomentumScorer.score().
        deltas: Output of compute_trend_delta() — when provided, direction
                is based on real period-over-period delta.
        n: Maximum number of results (ranked by score descending).
    """
    ranked = sorted(scores.items(), key=lambda x: x[1]["note_score"], reverse=True)[:n]
    results: List[Dict[str, Any]] = []
    for note, data in ranked:
        score = data["note_score"]
        if deltas is not None and note in deltas:
            direction = deltas[note]["direction"]
        else:
            direction = _heuristic_direction(score)
        results.append(
            {
                "note": note,
                "score": score,
                "direction": direction,
                "drivers": data.get("drivers", []),
            }
        )
    return results


def _heuristic_direction(score: float) -> str:
    """Fallback direction when no delta is available (first run)."""
    if score >= 2.0:
        return "up"
    if score >= 0.5:
        return "flat"
    return "down"


def top_notes(
    scores: Dict[str, Dict[str, Any]], n: int = 10
) -> List[tuple]:
    """Return top-N notes sorted by note_score descending.

    Returns:
        List of (note_name, score_dict) tuples.
    """
    return sorted(scores.items(), key=lambda x: x[1]["note_score"], reverse=True)[:n]


def trend_direction(score: float) -> str:
    """Heuristic trend direction based on absolute score.

    Used as fallback when no historical baseline exists (first run).

    ↑  strong absolute momentum  (score ≥ 2.0)
    →  steady                    (score ≥ 0.5)
    ↓  weak signal               (score < 0.5)
    """
    if score >= 2.0:
        return "↑"
    if score >= 0.5:
        return "→"
    return "↓"
