import uuid

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, pg_enum, uuid_pk
from app.models.enums import RefundStatus


class Refund(Base, TimestampMixin):
    __tablename__ = "refunds"
    __table_args__ = (CheckConstraint("amount_paise > 0", name="amount_positive"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id"), index=True)
    dispute_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("disputes.id", ondelete="SET NULL"))
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[RefundStatus] = mapped_column(pg_enum(RefundStatus), default=RefundStatus.REQUESTED)
    provider_refund_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    reason: Mapped[str] = mapped_column(Text)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
