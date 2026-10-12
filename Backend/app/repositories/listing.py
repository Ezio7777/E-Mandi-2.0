import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import Grade, ListingStatus
from app.models.listing import Listing

_GRADE_ORDER = [Grade.A, Grade.B, Grade.C, Grade.D]


def grades_at_least(min_grade: Grade) -> list[Grade]:
    return _GRADE_ORDER[: _GRADE_ORDER.index(min_grade) + 1]


@dataclass
class ListingFilters:
    statuses: list[ListingStatus] = field(default_factory=list)
    farmer_id: uuid.UUID | None = None
    crop: str | None = None  # case-insensitive exact
    category: str | None = None
    location: str | None = None  # case-insensitive contains
    min_price_paise: int | None = None
    max_price_paise: int | None = None
    min_grade: Grade | None = None
    min_available_kg: Decimal | None = None


class ListingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, listing_id: uuid.UUID) -> Listing | None:
        return await self.session.get(Listing, listing_id)

    async def get_for_update(self, listing_id: uuid.UUID) -> Listing | None:
        # FOR UPDATE OF listings: the joined `farmer` relationship must not be locked (outer join).
        return await self.session.scalar(
            select(Listing).where(Listing.id == listing_id).with_for_update(of=Listing)
            .execution_options(populate_existing=True))

    async def add(self, listing: Listing) -> Listing:
        self.session.add(listing)
        await self.session.flush()
        return listing

    async def search(self, f: ListingFilters, cursor: tuple[datetime, uuid.UUID] | None, limit: int) -> list[Listing]:
        """Keyset-paginated search. Returns up to limit+1 rows (extra row signals another page)."""
        stmt = select(Listing)
        if f.statuses:
            stmt = stmt.where(Listing.status.in_(f.statuses))
        if f.farmer_id:
            stmt = stmt.where(Listing.farmer_id == f.farmer_id)
        if f.crop:
            stmt = stmt.where(func.lower(Listing.crop_name) == f.crop.lower())
        if f.category:
            stmt = stmt.where(Listing.crop_category == f.category)
        if f.location:
            stmt = stmt.where(Listing.location.ilike(f"%{f.location}%"))
        if f.min_price_paise is not None:
            stmt = stmt.where(Listing.base_price_paise >= f.min_price_paise)
        if f.max_price_paise is not None:
            stmt = stmt.where(Listing.base_price_paise <= f.max_price_paise)
        if f.min_grade:
            stmt = stmt.where(Listing.ai_grade.in_(grades_at_least(f.min_grade)))
        if f.min_available_kg is not None:
            stmt = stmt.where(Listing.quantity_kg - Listing.reserved_kg >= f.min_available_kg)
        if cursor:
            stmt = stmt.where(tuple_(Listing.created_at, Listing.id) < tuple_(cursor[0], cursor[1]))
        stmt = stmt.order_by(Listing.created_at.desc(), Listing.id.desc()).limit(limit + 1)
        return list((await self.session.scalars(stmt)).unique().all())
