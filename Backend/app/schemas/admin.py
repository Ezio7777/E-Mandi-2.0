import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import (
    AnomalySeverity, AnomalyStatus, PendingActionStatus, PendingActionType, ReviewDecision,
)


class AnomalyOut(BaseModel):
    """A flag for human review - NOT a fraud verdict."""
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    rule_id: str
    severity: AnomalySeverity
    status: AnomalyStatus
    entity_type: str
    entity_id: str
    reason: str
    recommended_action: str
    details: dict[str, Any]
    detected_at: datetime
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    review_note: str | None


class AnomalyPage(BaseModel):
    items: list[AnomalyOut]
    next_cursor: str | None
    open_count: int


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    note: str = Field(min_length=5, max_length=1000)


class BanUserPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: uuid.UUID
    reason: str = Field(min_length=5, max_length=1000)
    anomaly_id: uuid.UUID | None = None


class ApproveGradePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    listing_id: uuid.UUID
    reason: str = Field(min_length=5, max_length=1000)
    anomaly_id: uuid.UUID | None = None


class ResolveDisputePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dispute_id: uuid.UUID
    outcome: Literal["SELLER_FAVOURED", "BUYER_REFUND"]
    resolution: str = Field(min_length=5, max_length=1000)
    anomaly_id: uuid.UUID | None = None


PAYLOADS: dict[PendingActionType, type[BaseModel]] = {
    PendingActionType.BAN_USER: BanUserPayload,
    PendingActionType.APPROVE_LOW_CONFIDENCE_GRADE: ApproveGradePayload,
    PendingActionType.RESOLVE_SERIOUS_DISPUTE: ResolveDisputePayload,
}


class ActionRequestIn(BaseModel):
    """Ask for a sensitive action. Nothing happens until a (different) admin approves it."""
    model_config = ConfigDict(extra="forbid")
    action_type: PendingActionType
    payload: dict[str, Any]

    @model_validator(mode="after")
    def _payload_shape(self) -> "ActionRequestIn":
        PAYLOADS[self.action_type].model_validate(self.payload)  # raises ValidationError -> 422
        return self


class AnomalyActionIn(BaseModel):
    """Escalate a flag into a pending action; the anomaly id is attached server-side."""
    model_config = ConfigDict(extra="forbid")
    action_type: PendingActionType
    payload: dict[str, Any]


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: str = Field(min_length=5, max_length=1000)


class PendingActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    action_type: PendingActionType
    status: PendingActionStatus
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    requested_by: uuid.UUID | None
    requested_via: str
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_reason: str | None
    executed_at: datetime | None
    result: dict[str, Any] | None
    created_at: datetime


class PendingActionPage(BaseModel):
    items: list[PendingActionOut]
    next_cursor: str | None
    pending_count: int


class RiskAssessIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: Literal["listing", "order", "payment"]
    entity_id: uuid.UUID


_ = ReviewDecision
