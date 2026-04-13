from typing import Optional

from pydantic import BaseModel, Field


class UnifiedSignal(BaseModel):
    item_id: str
    perfumes: list = Field(default_factory=list)
    brands: list = Field(default_factory=list)
    raw_mentions: list = Field(default_factory=list)
    ai_perfumes: list = Field(default_factory=list)
    ai_brands: list = Field(default_factory=list)
    ai_notes: list = Field(default_factory=list)
    ai_sentiment: Optional[str] = None
    ai_confidence: Optional[float] = None
    source_type: Optional[str] = None
    channel_name: Optional[str] = None
    influence_score: Optional[float] = None
    credibility_score: Optional[float] = None
