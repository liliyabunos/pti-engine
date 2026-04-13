from typing import Optional

from perfume_trend_sdk.core.models.unified_signal import UnifiedSignal


class SignalBuilder:
    def build(
        self,
        perfume_result: dict,
        brand_result: dict,
        resolved_result: dict,
        ai_result: Optional[dict] = None,
        source_result: Optional[dict] = None,
    ) -> UnifiedSignal:
        return UnifiedSignal(
            item_id=perfume_result["item_id"],
            perfumes=resolved_result["resolved_perfumes"],
            brands=brand_result["brand_mentions"],
            raw_mentions=perfume_result["perfume_mentions"],
            ai_perfumes=ai_result.get("perfumes", []) if ai_result else [],
            ai_brands=ai_result.get("brands", []) if ai_result else [],
            ai_notes=ai_result.get("notes", []) if ai_result else [],
            ai_sentiment=ai_result.get("sentiment") if ai_result else None,
            ai_confidence=ai_result.get("confidence") if ai_result else None,
            source_type=source_result.get("source_type") if source_result else None,
            channel_name=source_result.get("channel_name") if source_result else None,
            influence_score=source_result.get("influence_score") if source_result else None,
            credibility_score=source_result.get("credibility_score") if source_result else None,
        )
