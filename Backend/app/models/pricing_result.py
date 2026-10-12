import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk


class PricingResult(Base):
    """Output of the Smart Pricing Agent. The NUMBERS are deterministic; `explanation_provider` records whether
    the text came from an LLM (gemini/openai) or the deterministic template."""
    __tablename__ = "pricing_results"
    __table_args__ = (CheckConstraint("range_min_paise <= suggested_paise AND suggested_paise <= range_max_paise",
                                      name="range_contains_suggested"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), index=True)
    grading_result_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crop_grading_results.id", ondelete="SET NULL"))
    execution_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_executions.id", ondelete="SET NULL"))
    suggested_paise: Mapped[int] = mapped_column(BigInteger)
    range_min_paise: Mapped[int] = mapped_column(BigInteger)
    range_max_paise: Mapped[int] = mapped_column(BigInteger)
    reference_paise: Mapped[int] = mapped_column(BigInteger)
    trend: Mapped[str] = mapped_column(String(10))
    scope: Mapped[str] = mapped_column(String(20))
    data_points: Mapped[int] = mapped_column(Integer)
    is_sample: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(300))
    explanation: Mapped[str] = mapped_column(Text)
    explanation_provider: Mapped[str] = mapped_column(String(20), default="deterministic")  # deterministic|gemini|openai
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    factors: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
