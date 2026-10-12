import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk


class PaymentEvent(Base):
    """Webhook/lifecycle event log. UNIQUE(provider, provider_event_id) is the duplicate-event guard."""
    __tablename__ = "payment_events"
    __table_args__ = (UniqueConstraint("provider", "provider_event_id", name="uq_payment_events_provider_event"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    provider_event_id: Mapped[str] = mapped_column(String(150))
    event_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSONB)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
