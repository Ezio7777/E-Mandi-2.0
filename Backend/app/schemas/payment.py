import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import ConfigDict, Field, field_validator

from app.models.enums import PaymentStatus, RefundStatus
from app.schemas.common import CamelModel
from app.schemas.listing import Rupees


class PaymentCreate(CamelModel):
    """No amount field on purpose: the backend always charges the order's server-computed total."""
    model_config = ConfigDict(extra="forbid")
    order_id: uuid.UUID


class CheckoutOut(CamelModel):
    provider: str
    key_id: str  # PUBLIC key id only (never a secret)
    provider_order_id: str
    amount: Rupees
    amount_paise: int
    currency: str


class RefundOut(CamelModel):
    id: uuid.UUID
    amount: Rupees
    status: RefundStatus
    reason: str
    created_at: datetime


class PaymentOut(CamelModel):
    id: uuid.UUID
    order_id: uuid.UUID
    status: PaymentStatus
    amount: Rupees
    currency: str
    provider: str
    method: str | None
    failure_reason: str | None
    created_at: datetime
    checkout: CheckoutOut | None = None  # only for the paying buyer while the payment is still open
    refunds: list[RefundOut] = []


class RefundCreate(CamelModel):
    model_config = ConfigDict(extra="forbid")
    amount: Decimal | None = None  # rupees; omitted = refund the full remaining amount
    reason: str = Field(min_length=5, max_length=500)

    @field_validator("amount")
    @classmethod
    def _amt(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and (v <= 0 or v != v.quantize(Decimal("0.01"))):
            raise ValueError("amount must be positive with at most 2 decimal places")
        return v


class SimulateRequest(CamelModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["success", "failure"]


class WebhookAck(CamelModel):
    status: str
