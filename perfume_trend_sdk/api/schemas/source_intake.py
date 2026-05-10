from __future__ import annotations

"""SOURCE-INTAKE-V1A — Pydantic schemas for source intake admin API."""

from typing import List, Optional
from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Enums (as string constants — avoids Python 3.9 enum overhead)
# ---------------------------------------------------------------------------

CANDIDATE_STATUSES = {
    "PENDING_VERIFICATION",
    "VERIFIED_ADD_READY",
    "SKIP_DUPLICATE",
    "SKIP_INACTIVE",
    "NEEDS_OPERATOR_REVIEW",
    "OPERATOR_APPROVED",
    "OPERATOR_REJECTED",
    "DEFERRED",
    "BLOCKED_BY_API_PERMISSION",
    "APPLIED",
    "APPLY_FAILED",
    "PRODUCTION_VERIFIED",
}

# Statuses eligible for batch apply
APPLY_ELIGIBLE_STATUSES = {"VERIFIED_ADD_READY", "OPERATOR_APPROVED"}

# Terminal statuses — no further transitions allowed
TERMINAL_STATUSES = {
    "SKIP_DUPLICATE",
    "SKIP_INACTIVE",
    "OPERATOR_REJECTED",
    "PRODUCTION_VERIFIED",
}


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------

class BatchSummary(BaseModel):
    id: str
    batch_label: str
    platform: str
    description: Optional[str] = None
    status: str
    candidate_count: int
    applied_count: int
    created_at: Optional[str] = None
    created_by: str
    applied_at: Optional[str] = None
    applied_by: Optional[str] = None
    verified_at: Optional[str] = None
    # Counts by status (computed on list)
    count_verified_add_ready: int = 0
    count_needs_review: int = 0
    count_applied: int = 0
    count_operator_approved: int = 0


class BatchListResponse(BaseModel):
    batches: List[BatchSummary]
    total: int


# ---------------------------------------------------------------------------
# Candidate
# ---------------------------------------------------------------------------

class CandidateRow(BaseModel):
    id: str
    batch_id: str
    platform: str
    candidate_name: str
    input_url: str
    resolved_platform_id: Optional[str] = None
    resolved_title: Optional[str] = None
    subscriber_count: Optional[int] = None
    total_content_count: Optional[int] = None
    recent_content_count: Optional[int] = None
    recent_titles_sample: Optional[str] = None  # JSON string
    resolve_method: Optional[str] = None
    confidence: Optional[str] = None
    status: str
    decision_reason: Optional[str] = None
    operator_override_url: Optional[str] = None
    operator_notes: Optional[str] = None
    quality_tier: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    applied_at: Optional[str] = None
    apply_error: Optional[str] = None
    created_at: Optional[str] = None


class CandidateListResponse(BaseModel):
    candidates: List[CandidateRow]
    total: int
    batch_id: str


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class RejectRequest(BaseModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def reason_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("rejection reason must not be empty")
        return v.strip()


class UpdateCandidateRequest(BaseModel):
    operator_override_url: Optional[str] = None
    operator_notes: Optional[str] = None


class PersistBatchRequest(BaseModel):
    """Payload posted by the CLI script to persist a verification run."""
    batch_label: str
    platform: str
    description: Optional[str] = None
    created_by: str
    candidates: List[CandidatePersistItem]


class CandidatePersistItem(BaseModel):
    candidate_name: str
    input_url: str
    resolved_platform_id: Optional[str] = None
    resolved_title: Optional[str] = None
    subscriber_count: Optional[int] = None
    total_content_count: Optional[int] = None
    recent_content_count: Optional[int] = None
    recent_titles_sample: Optional[str] = None
    resolve_method: Optional[str] = None
    confidence: Optional[str] = None
    status: str
    decision_reason: Optional[str] = None
    quality_tier: Optional[str] = None


# ---------------------------------------------------------------------------
# Apply / verify response
# ---------------------------------------------------------------------------

class ApplyResult(BaseModel):
    batch_id: str
    applied: int
    skipped: int
    failed: int
    details: List[dict]


class ProductionVerifyResult(BaseModel):
    batch_id: str
    verified: int
    pending_ingestion: int
    details: List[dict]
