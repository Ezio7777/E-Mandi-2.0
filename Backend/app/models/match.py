import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, pg_enum, uuid_pk
from app.models.enums import MatchStatus


class Match(Base):
    """One ranked candidate for a buyer requirement. All five factor scores (0..1) plus `breakdown` (weights and
    the requirement/listing inputs at match time) make every match reproducible and explainable."""
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("requirement_id", "listing_id", name="uq_matches_pair"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("buyer_requirements.id", ondelete="CASCADE"), index=True)
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), index=True)
    score: Mapped[float] = mapped_column(Float)  # weighted total, 0..1
    grade_score: Mapped[float] = mapped_column(Float, server_default=text("0"))
    quantity_score: Mapped[float] = mapped_column(Float, server_default=text("0"))
    location_score: Mapped[float] = mapped_column(Float, server_default=text("0"))
    price_score: Mapped[float] = mapped_column(Float, server_default=text("0"))
    availability_score: Mapped[float] = mapped_column(Float, server_default=text("0"))
    reasons: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))  # [{factor, matched, detail}]
    breakdown: Mapped[dict] = mapped_column(JSONB)  # weights + inputs snapshot (reproducibility)
    distance_km: Mapped[float | None] = mapped_column(Float)
    search_step: Mapped[int] = mapped_column(Integer, server_default=text("0"))  # radius step where it was first found
    rank: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    execution_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_executions.id", ondelete="SET NULL"))
    explanation: Mapped[str | None] = mapped_column(Text)
    status: Mapped[MatchStatus] = mapped_column(pg_enum(MatchStatus), default=MatchStatus.SUGGESTED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
