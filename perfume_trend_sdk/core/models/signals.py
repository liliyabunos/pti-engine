from pydantic import BaseModel, Field


class ExtractedSignals(BaseModel):
    item_id: str
    perfume_mentions: list = Field(default_factory=list)
    brand_mentions: list = Field(default_factory=list)
    note_mentions: list = Field(default_factory=list)


class ResolvedSignals(BaseModel):
    item_id: str
    resolved_perfumes: list = Field(default_factory=list)
    unresolved_mentions: list = Field(default_factory=list)
