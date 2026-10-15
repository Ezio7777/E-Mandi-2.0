import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, pg_enum, uuid_pk
from app.models.enums import OrderStatus

if TYPE_CHECKING:
    from app.models.order_item import OrderItem
    from app.models.user import User


class Order(Base, TimestampMixin):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("total_amount_paise >= 0", name="total_non_negative"),
        UniqueConstraint("buyer_id", "idempotency_key", name="uq_orders_buyer_idempotency"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    buyer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    farmer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    requirement_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("buyer_requirements.id", ondelete="SET NULL"))
    match_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("matches.id", ondelete="SET NULL"))  # accepted match
    status: Mapped[OrderStatus] = mapped_column(pg_enum(OrderStatus), default=OrderStatus.PENDING, index=True)
    total_amount_paise: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    reservation_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    delivery_address: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    stock_committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # set when payment commits the sale
    restocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # set once a full refund returned the stock

    # read-only name lookups (selectin, NOT joined: orders are locked with FOR UPDATE)
    buyer: Mapped["User"] = relationship(foreign_keys="Order.buyer_id", lazy="selectin", viewonly=True)
    farmer: Mapped["User"] = relationship(foreign_keys="Order.farmer_id", lazy="selectin", viewonly=True)

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", lazy="selectin", cascade="all, delete-orphan")
