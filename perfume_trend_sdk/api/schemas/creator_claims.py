from __future__ import annotations

"""
Pydantic schemas for the C2 Creator Claim API.
"""

from typing import List, Optional

from pydantic import BaseModel, field_validator


class ClaimCreateRequest(BaseModel):
    platform: str
    creator_id: str
    claim_method: str   # bio_code | screenshot | manual_review
    evidence_url: str   # required: public URL
    note: Optional[str] = None

    @field_validator("claim_method")
    @classmethod
    def _validate_method(cls, v: str) -> str:
        allowed = {"bio_code", "screenshot", "manual_review"}
        if v not in allowed:
            raise ValueError(f"claim_method must be one of {allowed}")
        return v

    @field_validator("evidence_url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("evidence_url must be a valid http/https URL")
        return v

    @field_validator("platform")
    @classmethod
    def _validate_platform(cls, v: str) -> str:
        allowed = {"youtube", "tiktok", "instagram", "reddit", "other"}
        if v not in allowed:
            raise ValueError(f"platform must be one of {allowed}")
        return v


class ClaimResponse(BaseModel):
    claim_id: str
    platform: str
    creator_id: str
    claim_status: str
    claim_method: str
    evidence_url: Optional[str] = None
    # Returned once for bio_code claims — never stored or re-returned
    verification_code: Optional[str] = None
    verification_code_expires_at: Optional[str] = None
    message: str
    claimed_at: Optional[str] = None
    verified_at: Optional[str] = None
    reviewed_at: Optional[str] = None
    rejection_reason: Optional[str] = None


class ClaimSummary(BaseModel):
    """Claim entry returned by GET /me — verification_code never included."""
    claim_id: str
    platform: str
    creator_id: str
    claim_status: str
    claim_method: str
    evidence_url: Optional[str] = None
    claimed_at: Optional[str] = None
    verified_at: Optional[str] = None
    reviewed_at: Optional[str] = None
    rejection_reason: Optional[str] = None


class ClaimListResponse(BaseModel):
    claims: List[ClaimSummary]
