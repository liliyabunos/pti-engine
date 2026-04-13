from typing import Optional

from pydantic import BaseModel


class CanonicalContentItem(BaseModel):
    id: str
    source_platform: str
    source_account: Optional[str] = None
    source_url: Optional[str] = None
    title: Optional[str] = None
    text_content: Optional[str] = None
    published_at: Optional[str] = None
    collected_at: Optional[str] = None
    raw_payload: dict
