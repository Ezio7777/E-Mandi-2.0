import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from pydantic import ConfigDict, Field, PlainSerializer, field_validator

from app.models.enums import CropCategory, Grade, ListingStatus
from app.schemas.common import CamelModel

Rupees = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]
Kg = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]


def _check_price(v: Decimal | None) -> Decimal | None:
    if v is None:
        return v
    if v <= 0 or v > Decimal("100000"):
        raise ValueError("Price per kg must be between 0.01 and 100000")
    if v != v.quantize(Decimal("0.01")):
        raise ValueError("Price can have at most 2 decimal places")
    return v


def _check_qty(v: Decimal | None) -> Decimal | None:
    if v is None:
        return v
    if v <= 0 or v > Decimal("1000000"):
        raise ValueError("Quantity must be between 0.001 and 1,000,000 kg")
    if v != v.quantize(Decimal("0.001")):
        raise ValueError("Quantity can have at most 3 decimal places")
    return v


def _check_harvest(v: date | None) -> date | None:
    if v and not (date.today() - timedelta(days=365) <= v <= date.today() + timedelta(days=60)):
        raise ValueError("Harvest date must be within the last year or the next 60 days")
    return v


class ListingCreate(CamelModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    crop_name: str = Field(min_length=2, max_length=120)
    crop_category: CropCategory = CropCategory.OTHER
    description: str | None = Field(None, max_length=2000)
    quantity_kg: Decimal
    base_price: Decimal  # rupees per kg
    location: str = Field(min_length=2, max_length=200)
    state: str | None = Field(None, max_length=120)
    harvest_date: date | None = None

    _p = field_validator("base_price")(_check_price)
    _q = field_validator("quantity_kg")(_check_qty)
    _h = field_validator("harvest_date")(_check_harvest)


class ListingUpdate(CamelModel):
    """PATCH semantics. ai_grade / status / suggested_price are NOT client-settable."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    crop_name: str | None = Field(None, min_length=2, max_length=120)
    crop_category: CropCategory | None = None
    description: str | None = Field(None, max_length=2000)
    quantity_kg: Decimal | None = None
    base_price: Decimal | None = None
    location: str | None = Field(None, min_length=2, max_length=200)
    state: str | None = Field(None, max_length=120)
    harvest_date: date | None = None

    _p = field_validator("base_price")(_check_price)
    _q = field_validator("quantity_kg")(_check_qty)
    _h = field_validator("harvest_date")(_check_harvest)


class FarmerPublic(CamelModel):
    id: uuid.UUID
    name: str


class ListingOut(CamelModel):
    id: uuid.UUID
    farmer: FarmerPublic
    crop_name: str
    crop_category: CropCategory
    description: str | None
    quantity_kg: Kg
    reserved_kg: Kg
    available_kg: Kg
    base_price: Rupees
    suggested_price: Rupees | None
    ai_grade: Grade | None
    grade_confidence: float | None
    status: ListingStatus
    location: str
    state: str | None
    harvest_date: date | None
    primary_image_url: str | None = None
    image_count: int = 0
    verified_document_count: int = 0  # certificates an admin has verified
    created_at: datetime
    updated_at: datetime


class ListingPage(CamelModel):
    items: list[ListingOut]
    next_cursor: str | None


class InventoryItemOut(CamelModel):
    listing_id: uuid.UUID
    crop_name: str
    status: ListingStatus
    quantity_kg: Kg
    reserved_kg: Kg
    available_kg: Kg


class InventoryAdjust(CamelModel):
    model_config = ConfigDict(extra="forbid")
    quantity_kg: Decimal  # NEW TOTAL quantity
    reason: str = Field(min_length=3, max_length=300)

    _q = field_validator("quantity_kg")(_check_qty)


def listing_state(l: Any) -> dict[str, Any]:
    """Audit snapshot (JSON-safe)."""
    return {"crop_name": l.crop_name, "crop_category": l.crop_category.value, "quantity_kg": str(l.quantity_kg),
            "base_price_paise": l.base_price_paise, "location": l.location, "state": l.state,
            "harvest_date": l.harvest_date.isoformat() if l.harvest_date else None,
            "description": l.description, "status": l.status.value}
