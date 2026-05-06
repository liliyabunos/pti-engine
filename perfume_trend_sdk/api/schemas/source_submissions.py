from __future__ import annotations

"""
Pydantic schemas for Submit a Source MVP (POST /api/v1/source-submissions).
"""

from typing import Optional
from pydantic import BaseModel, field_validator


class SourceSubmissionRequest(BaseModel):
    url: str
    terms_accepted: bool
    submitted_by_user_id: Optional[str] = None
    submitted_by_email: Optional[str] = None

    @field_validator("url")
    @classmethod
    def url_must_be_nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("URL must not be empty")
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("URL must start with http:// or https://")
        return v

    @field_validator("terms_accepted")
    @classmethod
    def terms_must_be_accepted(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Terms must be accepted to submit a source")
        return v


class SourceSubmissionResponse(BaseModel):
    id: int
    normalized_url: str
    platform: Optional[str]
    status: str
    message: str
