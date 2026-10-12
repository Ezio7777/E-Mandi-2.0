"""Pricing contract. The frontend expects camelCase (suggested, rangeMin, rangeMax, referencePrice, trend,
explanation, source); the alias mapping is explicit here and applied on output (FastAPI serialises by alias)."""
from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.schemas.listing import Rupees


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PriceFactorOut(CamelModel):
    name: str
    effect_pct: float  # -> effectPct
    detail: str


class PricingOut(CamelModel):
    suggested: Rupees
    range_min: Rupees  # -> rangeMin
    range_max: Rupees  # -> rangeMax
    reference_price: Rupees  # -> referencePrice
    trend: Literal["up", "down", "stable"]
    explanation: str
    source: str
    # additive (not part of the original contract; safe for the frontend to ignore)
    scope: Literal["local", "national_fallback"]
    data_points: int
    is_sample: bool
    factors: list[PriceFactorOut]


class PricingResultOut(PricingOut):
    """Persisted Smart Pricing Agent result (frontend contract fields + provenance)."""
    pricing_id: str
    listing_id: str
    explanation_provider: Literal["deterministic", "gemini", "openai"]
    created_at: str


class JobAccepted(CamelModel):
    job_id: str  # -> jobId (agent_executions.id)


class JobStatusOut(CamelModel):
    job_id: str
    agent: str
    status: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "REVIEW_REQUIRED"]
    listing_id: str | None
    provider: str | None
    fallback_used: bool
    summary: str | None
    attempt: int
    started_at: str | None
    completed_at: str | None
    duration_ms: int | None
