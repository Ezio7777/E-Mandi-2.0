import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, pg_enum, uuid_pk
from app.models.enums import Grade, ReviewDecision


class GradingReview(Base):
    """Admin decision, stored separately so the original AI result is never overwritten."""
    __tablename__ = "grading_reviews"

    id: Mapped[uuid.UUID] = uuid_pk()
    grading_result_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_grading_results.id"), index=True)
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), index=True)
    original_result: Mapped[dict] = mapped_column(JSONB)
    decision: Mapped[ReviewDecision] = mapped_column(pg_enum(ReviewDecision))
    final_grade: Mapped[Grade | None] = mapped_column(pg_enum(Grade))
    admin_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
