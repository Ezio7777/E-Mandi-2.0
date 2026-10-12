import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, pg_enum, uuid_pk
from app.models.enums import PendingActionStatus, PendingActionType


class PendingAction(Base):
    """Human-in-the-loop queue. Agents/rules may only create rows here; only an admin decision executes."""
    __tablename__ = "pending_actions"

    id: Mapped[uuid.UUID] = uuid_pk()
    action_type: Mapped[PendingActionType] = mapped_column(pg_enum(PendingActionType))
    payload: Mapped[dict] = mapped_column(JSONB)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str] = mapped_column(String(64))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    requested_via: Mapped[str] = mapped_column(String(30), default="admin")  # admin | agent | system
    status: Mapped[PendingActionStatus] = mapped_column(
        pg_enum(PendingActionStatus), default=PendingActionStatus.PENDING, index=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
