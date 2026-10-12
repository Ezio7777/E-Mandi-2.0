import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, pg_enum, uuid_pk
from app.models.enums import Grade, GradingProvider


class CropGradingResult(Base):
    """Immutable record of a normalized (Pydantic-validated) AI result. image_sha256 doubles as the cache key."""
    __tablename__ = "crop_grading_results"

    id: Mapped[uuid.UUID] = uuid_pk()
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), index=True)
    image_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("listing_images.id", ondelete="SET NULL"))
    image_sha256: Mapped[str] = mapped_column(String(64), index=True)
    grade: Mapped[Grade] = mapped_column(pg_enum(Grade))
    confidence: Mapped[float] = mapped_column(Float)
    defect_percentage: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    issues: Mapped[list] = mapped_column(JSONB, default=list)
    provider: Mapped[GradingProvider] = mapped_column(pg_enum(GradingProvider))
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    from_cache: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
