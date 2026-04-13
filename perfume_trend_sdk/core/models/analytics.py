from typing import Optional

from pydantic import BaseModel, Field


class TrendSignal(BaseModel):
    name: str
    mention_count: int
    source: Optional[str] = None
    timeframe: Optional[str] = None


class TrendReport(BaseModel):
    generated_at: str
    top_perfumes: list = Field(default_factory=list)
