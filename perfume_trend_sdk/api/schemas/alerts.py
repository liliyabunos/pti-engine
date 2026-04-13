from __future__ import annotations

"""Pydantic schemas for the alerts API."""

from typing import Optional

from pydantic import BaseModel, Field, model_validator

from perfume_trend_sdk.db.market.alert import THRESHOLD_REQUIRED, VALID_CONDITION_TYPES


class AlertCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    entity_id: str = Field(..., min_length=1, max_length=255)
    entity_type: str = Field(..., pattern="^(perfume|brand|note)$")
    condition_type: str
    threshold_value: Optional[float] = None
    cooldown_hours: int = Field(default=24, ge=1, le=8760)

    @model_validator(mode="after")
    def validate_condition(self) -> "AlertCreate":
        if self.condition_type not in VALID_CONDITION_TYPES:
            raise ValueError(
                f"Invalid condition_type '{self.condition_type}'. "
                f"Allowed: {sorted(VALID_CONDITION_TYPES)}"
            )
        if self.condition_type in THRESHOLD_REQUIRED and self.threshold_value is None:
            raise ValueError(
                f"condition_type '{self.condition_type}' requires a threshold_value."
            )
        return self


class AlertPatch(BaseModel):
    is_active: Optional[bool] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    cooldown_hours: Optional[int] = Field(default=None, ge=1, le=8760)


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------

class AlertRow(BaseModel):
    id: str
    name: str
    entity_id: str
    entity_type: str
    canonical_name: Optional[str]
    ticker: Optional[str]
    condition_type: str
    threshold_value: Optional[float]
    cooldown_hours: int
    is_active: bool
    delivery_type: str
    last_triggered_at: Optional[str]
    created_at: str
    updated_at: str


class AlertEventRow(BaseModel):
    id: str
    alert_id: str
    alert_name: Optional[str]
    entity_id: str
    entity_type: str
    canonical_name: Optional[str]
    triggered_at: str
    status: str
    reason_json: Optional[str]
    created_at: str


class AlertListResponse(BaseModel):
    alerts: list[AlertRow]


class AlertHistoryResponse(BaseModel):
    events: list[AlertEventRow]
    total: int
