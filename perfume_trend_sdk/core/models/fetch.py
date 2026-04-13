from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class FetchCursor(BaseModel):
    source_name: str
    cursor_value: Optional[str] = None
    updated_at: datetime


class FetchSessionResult(BaseModel):
    source_name: str
    fetched_count: int
    raw_items: list = Field(default_factory=list)
