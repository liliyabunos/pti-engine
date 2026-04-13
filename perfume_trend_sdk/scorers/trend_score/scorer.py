from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, List

from perfume_trend_sdk.core.models.unified_signal import UnifiedSignal


def build_trend_counts(resolved_signals: List[Dict[str, Any]]) -> Counter:
    counter: Counter = Counter()

    for signal in resolved_signals:
        entities = json.loads(signal["resolved_entities_json"])
        for e in entities:
            counter[e["canonical_name"]] += 1

    return counter


class TrendScorer:
    def score(self, unified_signals: list) -> dict:
        mention_counts: dict = {}

        for signal in unified_signals:
            if isinstance(signal, UnifiedSignal):
                if signal.perfumes:
                    perfumes = signal.perfumes
                elif signal.ai_perfumes:
                    perfumes = [
                        p.get("product")
                        for p in signal.ai_perfumes
                        if p.get("product")
                    ]
                else:
                    continue
            else:
                perfumes = signal.get("perfume_mentions", [])

            weight = signal.influence_score / 100 if isinstance(signal, UnifiedSignal) and signal.influence_score is not None else 1.0

            if isinstance(signal, UnifiedSignal):
                if signal.ai_sentiment == "positive":
                    weight *= 1.2
                elif signal.ai_sentiment == "negative":
                    weight *= 0.5

                if signal.ai_confidence is not None:
                    weight *= signal.ai_confidence

            for perfume in perfumes:
                mention_counts[perfume] = mention_counts.get(perfume, 0) + weight

        return {
            "total_items": len(unified_signals),
            "total_mentions": sum(mention_counts.values()),
            "mention_counts": mention_counts,
        }
