import uuid
from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field, field_validator

from app.models.enums import Grade, GradingProvider, ReviewDecision
from app.schemas.common import CamelModel


class RawGrading(CamelModel):
    """Strict contract for what a vision model may return. Anything else is rejected (never trusted)."""
    model_config = ConfigDict(extra="forbid")
    grade: Grade
    confidence: float = Field(ge=0.0, le=1.0)
    defect_percentage: float = Field(ge=0.0, le=100.0)
    reason: str = Field(min_length=1, max_length=500)
    issues: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("issues")
    @classmethod
    def _issues(cls, v: list[str]) -> list[str]:
        cleaned = [i.strip() for i in v if i.strip()]
        if any(len(i) > 100 for i in cleaned):
            raise ValueError("issue text too long")
        return cleaned

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        return v.strip()


class GradingOutput(RawGrading):
    """Internal normalized result (the schema the rest of the system consumes)."""
    provider: Literal["gemini", "openai"]
    fallback_used: bool = False


class GradingResultOut(CamelModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    listing_id: uuid.UUID
    grade: Grade
    confidence: float
    defect_percentage: float
    reason: str
    issues: list[str]
    provider: GradingProvider
    fallback_used: bool
    from_cache: bool
    requires_review: bool
    created_at: datetime


class ReviewRequest(CamelModel):
    model_config = ConfigDict(extra="forbid")
    decision: ReviewDecision
    final_grade: Grade | None = None
    reason: str = Field(min_length=5, max_length=1000)

    @field_validator("final_grade")
    @classmethod
    def _noop(cls, v: Grade | None) -> Grade | None:
        return v


class ReviewQueueItem(CamelModel):
    listing_id: uuid.UUID
    crop_name: str
    farmer_id: uuid.UUID
    ai_result: GradingResultOut | None
    flags: list[str]
    submitted_at: datetime


from app.schemas.pricing import CamelModel, JobStatusOut, PricingResultOut  # noqa: E402


class GradingRequest(CamelModel):
    listing_id: uuid.UUID  # -> listingId


class GradingContractOut(CamelModel):
    """Frontend grading-result contract: grade, confidence, defectPercent, explanation, issues, provider, gradedAt,
    manualReviewRecommended (mapped explicitly from crop_grading_results)."""
    grade: Grade
    confidence: float
    defect_percent: float
    explanation: str
    issues: list[str]
    provider: str
    graded_at: datetime
    manual_review_recommended: bool
    fallback_used: bool
    from_cache: bool


class GradingJobOut(JobStatusOut):
    result: GradingContractOut | None = None
    pricing: PricingResultOut | None = None
