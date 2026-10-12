from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.listing import Rupees

Metric = Literal["signups", "listings", "orders", "gmv", "payments_failed", "disputes"]


class UsersStat(BaseModel):
    by_role: dict[str, int]
    new_in_window: int
    banned: int


class ListingsStat(BaseModel):
    by_status: dict[str, int]
    new_in_window: int
    awaiting_grading_review: int


class OrdersStat(BaseModel):
    by_status: dict[str, int]
    new_in_window: int
    gmv: Rupees                 # value of orders created in the window that reached PAID or later (excl. cancelled/refunded)
    average_order_value: Rupees | None


class PaymentsStat(BaseModel):
    succeeded: int
    failed: int
    success_rate: float | None
    refunded: Rupees            # refunds COMPLETED in the window


class RiskStat(BaseModel):
    disputes_open: int
    anomalies_open_by_severity: dict[str, int]
    pending_approvals: int


class OverviewOut(BaseModel):
    window_days: int
    generated_at: datetime
    users: UsersStat
    listings: ListingsStat
    orders: OrdersStat
    payments: PaymentsStat
    risk: RiskStat


class SeriesPoint(BaseModel):
    day: date
    value: float


class TimeseriesOut(BaseModel):
    metric: Metric
    unit: Literal["count", "rupees"]
    days: int
    points: list[SeriesPoint]   # one point per UTC day, zero-filled
    total: float


class TopCrop(BaseModel):
    crop: str
    listings: int
    total_kg: float
    average_price: Rupees


class TopCropsOut(BaseModel):
    window_days: int
    items: list[TopCrop]
