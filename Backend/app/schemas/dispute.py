import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DisputeStatus, OrderStatus, UserRole

Category = Literal["NOT_RECEIVED", "QUALITY_ISSUE", "QUANTITY_SHORTAGE", "WRONG_ITEM", "PAYMENT_ISSUE", "OTHER"]


class DisputeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    order_id: uuid.UUID
    category: Category
    description: str = Field(min_length=10, max_length=2000)


class EvidenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    note: str = Field(min_length=3, max_length=2000)


class EvidenceRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    from_party: Literal["buyer", "farmer", "both"]
    message: str = Field(min_length=5, max_length=1000)


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    outcome: Literal["SELLER_FAVOURED", "BUYER_REFUND"]
    resolution: str = Field(min_length=10, max_length=2000)


class DisputeRefundIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: float | None = Field(None, gt=0)  # rupees; omitted = full remaining amount
    reason: str | None = Field(None, min_length=5, max_length=500)


class PartyRef(BaseModel):
    id: uuid.UUID
    name: str
    role: UserRole


class TimelineEntry(BaseModel):
    kind: Literal["opened", "evidence", "admin_request"]
    by: uuid.UUID
    name: str
    role: UserRole
    note: str
    at: datetime


class DisputeOut(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    order_status: OrderStatus
    raised_by: PartyRef
    category: str
    description: str
    status: DisputeStatus
    timeline: list[TimelineEntry]
    resolution: str | None
    refund_required: bool
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DisputePage(BaseModel):
    items: list[DisputeOut]
    next_cursor: str | None
