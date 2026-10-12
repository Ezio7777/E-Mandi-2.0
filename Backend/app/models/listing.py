import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, Date, Float, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, pg_enum, uuid_pk
from app.models.enums import CropCategory, Grade, ListingStatus


class Listing(Base, TimestampMixin):
    """Prices are integer paise per kg. available_kg = quantity_kg - reserved_kg."""
    __tablename__ = "listings"
    __table_args__ = (
        CheckConstraint("quantity_kg >= 0", name="quantity_non_negative"),
        CheckConstraint("reserved_kg >= 0 AND reserved_kg <= quantity_kg", name="reserved_within_quantity"),
        CheckConstraint("base_price_paise > 0", name="base_price_positive"),
        Index("ix_listings_status_crop", "status", "crop_name"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    farmer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    crop_name: Mapped[str] = mapped_column(String(120), index=True)
    crop_category: Mapped[CropCategory] = mapped_column(pg_enum(CropCategory), default=CropCategory.OTHER)
    description: Mapped[str | None] = mapped_column(Text)
    quantity_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    reserved_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal(0))
    base_price_paise: Mapped[int] = mapped_column(BigInteger)
    suggested_price_paise: Mapped[int | None] = mapped_column(BigInteger)
    ai_grade: Mapped[Grade | None] = mapped_column(pg_enum(Grade))
    grade_confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[ListingStatus] = mapped_column(pg_enum(ListingStatus), default=ListingStatus.DRAFT, index=True)
    location: Mapped[str] = mapped_column(String(200), index=True)
    state: Mapped[str | None] = mapped_column(String(120))
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    harvest_date: Mapped[date | None] = mapped_column(Date)

    farmer: Mapped["User"] = relationship(lazy="joined", viewonly=True)  # noqa: F821

    images: Mapped[list["ListingImage"]] = relationship(  # noqa: F821
        back_populates="listing", lazy="selectin", order_by="ListingImage.created_at",
        cascade="all, delete-orphan")

    @property
    def available_kg(self) -> Decimal:
        return self.quantity_kg - self.reserved_kg
