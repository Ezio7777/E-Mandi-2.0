import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, pg_enum, uuid_pk
from app.models.enums import Grade, RequirementStatus


class BuyerRequirement(Base, TimestampMixin):
    __tablename__ = "buyer_requirements"
    __table_args__ = (CheckConstraint("quantity_kg > 0", name="quantity_positive"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    buyer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    crop_name: Mapped[str] = mapped_column(String(120), index=True)
    quantity_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    min_grade: Mapped[Grade] = mapped_column(pg_enum(Grade), default=Grade.C)
    location: Mapped[str] = mapped_column(String(200))
    max_price_paise: Mapped[int] = mapped_column(BigInteger)
    needed_by: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RequirementStatus] = mapped_column(pg_enum(RequirementStatus), default=RequirementStatus.OPEN)
