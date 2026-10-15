import uuid
from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field

from app.models.enums import DisputeStatus, OrderStatus, UserRole
from app.schemas.common import CamelModel

Category = Literal["NOT_RECEIVED", "QUALITY_ISSUE", "QUANTITY_SHORTAGE", "WRONG_ITEM", "PAYMENT_ISSUE", "OTHER"]


class DisputeCreate(CamelModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    order_id: uuid.UUID
    category: Category
    description: str = Field(min_length=10, max_length=2000)


class EvidenceIn(CamelModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    note: str = Field(min_length=3, max_length=2000)


class EvidenceRequestIn(CamelModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    from_party: Literal["buyer", "farmer", "both"]
    message: str = Field(min_length=5, max_length=1000)


class ResolveIn(CamelModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    outcome: Literal["SELLER_FAVOURED", "BUYER_REFUND"]
    resolution: str = Field(min_length=10, max_length=2000)


class DisputeRefundIn(CamelModel):
    model_config = ConfigDict(extra="forbid")
    amount: float | None = Field(None, gt=0)  # rupees; omitted = full remaining amount
    reason: str | None = Field(None, min_length=5, max_length=500)


class PartyRef(CamelModel):
    id: uuid.UUID
    name: str
    role: UserRole


class TimelineEntry(CamelModel):
    kind: Literal["opened", "evidence", "admin_request"]
    by: uuid.UUID
    name: str
    role: UserRole
    note: str
    at: datetime


class DisputeOut(CamelModel):
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


class DisputePage(CamelModel):
    items: list[DisputeOut]
    next_cursor: str | None
