import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import Grade, OrderStatus
from app.schemas.listing import Kg, Rupees, _check_qty


class OrderItemIn(BaseModel):
    """Deliberately has NO price/amount fields: the backend computes every amount from the listing's price."""
    model_config = ConfigDict(extra="forbid")
    listing_id: uuid.UUID
    quantity_kg: Decimal

    _q = field_validator("quantity_kg")(_check_qty)


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    items: list[OrderItemIn] = Field(min_length=1, max_length=10)
    delivery_address: str | None = Field(None, max_length=500)
    notes: str | None = Field(None, max_length=1000)
    match_id: uuid.UUID | None = None  # accepting a Buyer Matching Agent suggestion

    @model_validator(mode="after")
    def _unique_listings(self) -> "OrderCreate":
        ids = [i.listing_id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Each listing may appear only once per order")
        return self


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(None, min_length=3, max_length=500)


class PartyOut(BaseModel):
    id: uuid.UUID
    name: str


class OrderItemOut(BaseModel):
    listing_id: uuid.UUID
    crop_name: str
    quantity_kg: Kg
    unit_price: Rupees  # price per kg at order time (snapshot)
    line_total: Rupees
    grade: Grade | None


class OrderOut(BaseModel):
    id: uuid.UUID
    status: OrderStatus
    buyer: PartyOut
    farmer: PartyOut
    items: list[OrderItemOut]
    total_amount: Rupees
    currency: str
    reservation_expires_at: datetime | None
    delivery_address: str | None
    notes: str | None
    cancel_reason: str | None
    match_id: uuid.UUID | None
    requirement_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class OrderPage(BaseModel):
    items: list[OrderOut]
    next_cursor: str | None
