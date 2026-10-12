"""Inventory primitives. reserve/release/commit run INSIDE the caller's transaction (OrderService composes them
with order rows + audit so everything commits atomically). Every call takes a row lock (SELECT ... FOR UPDATE),
locking listings in a deterministic order to avoid deadlocks. This is what makes overselling impossible."""
import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import transactional
from app.core.errors import ConflictError, InsufficientStockError, NotFoundError
from app.models.enums import ListingStatus as L
from app.models.enums import UserRole
from app.models.listing import Listing
from app.models.user import User
from app.repositories.listing import ListingRepository
from app.schemas.listing import InventoryItemOut
from app.services.access import assert_owner_listing
from app.services.audit import Actor, AuditService, RequestContext
from app.services.transitions import LISTING_TRANSITIONS, assert_transition

Item = tuple[uuid.UUID, Decimal]
ZERO = Decimal(0)


def _set_status(listing: Listing, target: L) -> None:
    if listing.status != target:
        assert_transition(LISTING_TRANSITIONS, listing.status, target)
        listing.status = target


def _sorted(items: list[Item]) -> list[Item]:
    merged: dict[uuid.UUID, Decimal] = {}
    for lid, qty in items:
        merged[lid] = merged.get(lid, ZERO) + qty
    return sorted(merged.items(), key=lambda x: str(x[0]))


class InventoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.listings = ListingRepository(session)
        self.audit = AuditService(session)

    async def _lock(self, listing_id: uuid.UUID) -> Listing:
        listing = await self.listings.get_for_update(listing_id)
        if listing is None:
            raise NotFoundError("Listing not found")
        return listing

    async def reserve_many(self, items: list[Item]) -> dict[uuid.UUID, Listing]:
        out: dict[uuid.UUID, Listing] = {}
        for lid, qty in _sorted(items):
            if qty <= 0:
                raise ConflictError("Quantity must be positive")
            l = await self._lock(lid)
            if l.status != L.ACTIVE:
                raise InsufficientStockError("This listing is not available for purchase")
            if l.available_kg < qty:
                raise InsufficientStockError(f"Only {l.available_kg} kg available")
            l.reserved_kg = l.reserved_kg + qty
            if l.available_kg == 0:
                _set_status(l, L.RESERVED)
            out[lid] = l
        await self.session.flush()
        return out

    async def release_many(self, items: list[Item]) -> None:
        for lid, qty in _sorted(items):
            l = await self._lock(lid)
            l.reserved_kg = max(ZERO, l.reserved_kg - qty)
            if l.status == L.RESERVED and l.available_kg > 0:
                _set_status(l, L.ACTIVE)
        await self.session.flush()

    async def commit_sale_many(self, items: list[Item]) -> None:
        """Reserved stock becomes sold: total and reserved both decrease."""
        for lid, qty in _sorted(items):
            l = await self._lock(lid)
            if l.reserved_kg < qty:
                raise ConflictError("Reservation does not cover this quantity")
            l.quantity_kg, l.reserved_kg = l.quantity_kg - qty, l.reserved_kg - qty
            if l.quantity_kg == 0:
                _set_status(l, L.SOLD)
            elif l.available_kg == 0:
                _set_status(l, L.RESERVED)
            elif l.status == L.RESERVED:
                _set_status(l, L.ACTIVE)
        await self.session.flush()

    # ---- farmer-facing ----
    async def inventory_for(self, user: User) -> list[InventoryItemOut]:
        from app.repositories.listing import ListingFilters
        rows = await self.listings.search(ListingFilters(farmer_id=user.id), None, 200)
        return [InventoryItemOut(listing_id=r.id, crop_name=r.crop_name, status=r.status, quantity_kg=r.quantity_kg,
                                 reserved_kg=r.reserved_kg, available_kg=r.available_kg)
                for r in rows[:200] if r.status != L.ARCHIVED]

    async def adjust_quantity(self, user: User, listing_id: uuid.UUID, new_qty: Decimal, reason: str,
                              ctx: RequestContext) -> Listing:
        async with transactional(self.session):
            l = await self._lock(listing_id)
            assert_owner_listing(user, l)
            if l.status not in {L.DRAFT, L.ACTIVE, L.RESERVED, L.REVIEW_REQUIRED}:
                raise ConflictError(f"Quantity cannot be changed while the listing is {l.status.value}")
            if new_qty < l.reserved_kg:
                raise ConflictError(f"Quantity cannot be lower than the {l.reserved_kg} kg already reserved")
            before = {"quantity_kg": str(l.quantity_kg), "status": l.status.value}
            l.quantity_kg = new_qty
            if l.status == L.RESERVED and l.available_kg > 0:
                _set_status(l, L.ACTIVE)
            elif l.status == L.ACTIVE and l.available_kg == 0:
                _set_status(l, L.RESERVED)
            self.audit.record(action="inventory.adjusted", entity_type="listing", entity_id=l.id,
                              actor=Actor(user.id, user.role), ip=ctx.ip, metadata={"reason": reason},
                              previous_state=before, new_state={"quantity_kg": str(l.quantity_kg), "status": l.status.value})
        return l


_ = UserRole
