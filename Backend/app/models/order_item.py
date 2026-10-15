import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, pg_enum, uuid_pk
from app.models.enums import Grade
from app.models.order import Order

if TYPE_CHECKING:
    from app.models.listing import Listing


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (CheckConstraint("quantity_kg > 0", name="quantity_positive"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id"), index=True)
    quantity_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit_price_paise: Mapped[int] = mapped_column(BigInteger)  # snapshot at order time
    line_total_paise: Mapped[int] = mapped_column(BigInteger)
    grade_at_purchase: Mapped[Grade | None] = mapped_column(pg_enum(Grade))

    order: Mapped[Order] = relationship(back_populates="items")
    listing: Mapped["Listing"] = relationship(lazy="selectin", viewonly=True)
