import uuid

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, pg_enum, uuid_pk
from app.models.enums import PaymentStatus


class Payment(Base, TimestampMixin):
    """Marketplace payment record (provider sandbox). Not a regulated escrow."""
    __tablename__ = "payments"
    __table_args__ = (CheckConstraint("amount_paise > 0", name="amount_positive"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    payer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    provider_order_id: Mapped[str] = mapped_column(String(100), unique=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(100), index=True)
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[PaymentStatus] = mapped_column(pg_enum(PaymentStatus), default=PaymentStatus.CREATED)
    method: Mapped[str | None] = mapped_column(String(30))
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    failure_reason: Mapped[str | None] = mapped_column(Text)
