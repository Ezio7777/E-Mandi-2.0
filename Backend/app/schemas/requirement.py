import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import Grade, RequirementStatus
from app.schemas.listing import Kg, Rupees, _check_price, _check_qty


class RequirementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    crop_name: str = Field(min_length=2, max_length=120)
    quantity_kg: Decimal
    min_grade: Grade = Grade.C
    location: str = Field(min_length=2, max_length=200)
    max_price: Decimal  # rupees per kg
    needed_by: date | None = None
    notes: str | None = Field(None, max_length=1000)

    _q = field_validator("quantity_kg")(_check_qty)
    _p = field_validator("max_price")(_check_price)

    @field_validator("needed_by")
    @classmethod
    def _date(cls, v: date | None) -> date | None:
        if v and not (date.today() <= v <= date.today() + timedelta(days=180)):
            raise ValueError("needed_by must be today or within the next 180 days")
        return v


class RequirementOut(BaseModel):
    id: uuid.UUID
    crop_name: str
    quantity_kg: Kg
    min_grade: Grade
    location: str
    max_price: Rupees
    needed_by: date | None
    notes: str | None
    status: RequirementStatus
    created_at: datetime
    match_job_id: str | None = None  # the Buyer Matching Agent run triggered by this requirement (if any)
