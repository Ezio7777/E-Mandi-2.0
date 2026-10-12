"""Matching contract: [{ listingId, score, reasons: [{factor, matched, detail}] }] (+ additive fields).
`score` is 0-100 (percent). Internally scores are 0-1; the conversion happens here, explicitly."""
import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import Grade, MatchStatus
from app.schemas.listing import Kg, Rupees
from app.schemas.pricing import CamelModel, JobStatusOut


class ReasonOut(BaseModel):
    factor: str
    matched: bool
    detail: str


class MatchListingSummary(CamelModel):
    crop_name: str
    farmer_name: str
    price_per_kg: Rupees
    available_kg: Kg
    grade: Grade | None
    location: str


class MatchOut(CamelModel):
    match_id: uuid.UUID
    listing_id: uuid.UUID  # -> listingId
    score: float  # 0-100
    reasons: list[ReasonOut]
    # additive
    grade_score: float
    quantity_score: float
    location_score: float
    price_score: float
    availability_score: float
    distance_km: float | None
    rank: int
    status: MatchStatus
    listing: MatchListingSummary
    created_at: datetime


class MatchSetOut(CamelModel):
    requirement_id: uuid.UUID
    requested_kg: Kg
    covered_kg: Kg  # total stock across matches (may exceed requested)
    fully_covered: bool
    matches: list[MatchOut]


class MatchingJobOut(JobStatusOut):
    requirement_id: str | None = None
    match_count: int | None = None
