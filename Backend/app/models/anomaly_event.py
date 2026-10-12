import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, pg_enum, uuid_pk
from app.models.enums import AnomalySeverity, AnomalyStatus


class AnomalyEvent(Base):
    """A rule trigger is a flag for human review, never a fraud verdict."""
    __tablename__ = "anomaly_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    rule_id: Mapped[str] = mapped_column(String(60), index=True)
    severity: Mapped[AnomalySeverity] = mapped_column(pg_enum(AnomalySeverity))
    status: Mapped[AnomalyStatus] = mapped_column(
        pg_enum(AnomalyStatus), default=AnomalyStatus.FLAGGED_FOR_REVIEW, index=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    recommended_action: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)
