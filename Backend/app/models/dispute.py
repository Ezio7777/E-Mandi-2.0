import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, pg_enum, uuid_pk
from app.models.enums import DisputeStatus


class Dispute(Base, TimestampMixin):
    __tablename__ = "disputes"

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    raised_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[DisputeStatus] = mapped_column(pg_enum(DisputeStatus), default=DisputeStatus.OPEN, index=True)
    evidence: Mapped[list] = mapped_column(JSONB, default=list)  # [{by, note, s3_key?, at}]
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
