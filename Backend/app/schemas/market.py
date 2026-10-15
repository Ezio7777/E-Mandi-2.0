import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.schemas.common import CamelModel
from app.schemas.listing import Rupees


def _price(v: Decimal) -> Decimal:
    if v <= 0 or v > Decimal("100000"):
        raise ValueError("Price must be between 0.01 and 100000 per kg")
    if v != v.quantize(Decimal("0.01")):
        raise ValueError("Price can have at most 2 decimal places")
    return v


class MarketReportIn(CamelModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    crop: str = Field(min_length=2, max_length=120)
    location: str = Field(min_length=2, max_length=200)
    market: str = Field(min_length=2, max_length=200)
    min_price: Decimal
    max_price: Decimal
    average_price: Decimal
    report_date: date
    source: str = Field(min_length=2, max_length=200)
    is_sample: bool = False  # seeded demo/reference rows MUST set this so the UI never presents them as live

    _p = field_validator("min_price", "max_price", "average_price")(_price)

    @field_validator("report_date")
    @classmethod
    def _date(cls, v: date) -> date:
        if v > date.today() + timedelta(days=1):
            raise ValueError("report_date cannot be in the future")
        return v

    @model_validator(mode="after")
    def _order(self) -> "MarketReportIn":
        if not (self.min_price <= self.average_price <= self.max_price):
            raise ValueError("Require min_price <= average_price <= max_price")
        return self


class MarketReportsUpsert(CamelModel):
    model_config = ConfigDict(extra="forbid")
    reports: list[MarketReportIn] = Field(min_length=1, max_length=500)


class MarketReportOut(CamelModel):
    id: uuid.UUID
    crop: str
    location: str
    market: str
    min_price: Rupees
    max_price: Rupees
    average_price: Rupees
    report_date: date
    source: str
    is_sample: bool


class MarketSearchHit(CamelModel):
    report: MarketReportOut
    similarity: float | None = None


class MarketSearchOut(CamelModel):
    mode: Literal["semantic", "keyword"]
    crop: str | None
    hits: list[MarketSearchHit]


class UpsertResult(CamelModel):
    upserted: int
    embedding_job_queued: bool
