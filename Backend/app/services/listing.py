"""Listing lifecycle. Status changes go through assert_transition; clients can never set status/grade/suggested price."""
import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runtime import AgentExecutionService
from app.core.database import transactional
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.integrations.aws.image_url_resolver import ImageUrlResolver
from app.models.enums import AgentName
from app.models.enums import ListingStatus as L
from app.models.enums import UserRole
from app.models.listing import Listing
from app.models.user import User
from app.repositories.image import ImageRepository
from app.repositories.listing import ListingFilters, ListingRepository
from app.schemas.listing import FarmerPublic, ListingCreate, ListingOut, ListingPage, ListingUpdate, listing_state
from app.services.access import assert_can_view_listing, assert_owner_listing
from app.services.audit import Actor, AuditService, RequestContext
from app.services.transitions import LISTING_TRANSITIONS, assert_transition
from app.utils.money import paise_to_rupees, rupees_to_paise
from app.utils.pagination import decode_cursor, encode_cursor

log = get_logger(__name__)
EDITABLE = {L.DRAFT, L.ACTIVE, L.REVIEW_REQUIRED}
GradingEnqueue = Callable[[uuid.UUID, uuid.UUID], Awaitable[None]]  # (listing_id, execution_id)


class ListingService:
    def __init__(self, session: AsyncSession, resolver: ImageUrlResolver | None = None,
                 enqueue_grading: GradingEnqueue | None = None) -> None:
        self.session, self.resolver, self.enqueue_grading = session, resolver, enqueue_grading
        self.listings, self.images = ListingRepository(session), ImageRepository(session)
        self.audit = AuditService(session)

    async def to_out(self, l: Listing) -> ListingOut:
        primary = next((i for i in l.images if i.is_primary), None)
        url = await self.resolver.url_for(primary.s3_key) if (primary and self.resolver) else None
        return ListingOut(
            id=l.id, farmer=FarmerPublic(id=l.farmer_id, name=l.farmer.full_name), crop_name=l.crop_name,
            crop_category=l.crop_category, description=l.description, quantity_kg=l.quantity_kg,
            reserved_kg=l.reserved_kg, available_kg=l.available_kg, base_price=paise_to_rupees(l.base_price_paise),
            suggested_price=paise_to_rupees(l.suggested_price_paise) if l.suggested_price_paise else None,
            ai_grade=l.ai_grade, grade_confidence=l.grade_confidence, status=l.status, location=l.location,
            state=l.state, harvest_date=l.harvest_date, primary_image_url=url, image_count=len(l.images),
            created_at=l.created_at, updated_at=l.updated_at)

    async def create(self, user: User, data: ListingCreate, ctx: RequestContext) -> Listing:
        if user.role != UserRole.FARMER:
            raise ForbiddenError("Only farmers can create listings")
        async with transactional(self.session):
            l = await self.listings.add(Listing(
                farmer_id=user.id, crop_name=data.crop_name, crop_category=data.crop_category,
                description=data.description, quantity_kg=data.quantity_kg, reserved_kg=Decimal(0),
                base_price_paise=rupees_to_paise(data.base_price), location=data.location, state=data.state,
                harvest_date=data.harvest_date, status=L.DRAFT))
            self.audit.record(action="listing.created", entity_type="listing", entity_id=l.id,
                              actor=Actor(user.id, user.role), ip=ctx.ip, new_state=listing_state(l))
        return await self._reload(l.id)

    async def _reload(self, listing_id: uuid.UUID) -> Listing:
        l = await self.listings.get(listing_id)
        assert l is not None
        await self.session.refresh(l)  # server-side columns (updated_at) are expired after UPDATE
        await self.session.refresh(l, ["images"])
        return l

    async def get(self, user: User, listing_id: uuid.UUID) -> Listing:
        return assert_can_view_listing(user, await self.listings.get(listing_id))

    async def update(self, user: User, listing_id: uuid.UUID, data: ListingUpdate, ctx: RequestContext) -> Listing:
        changes = data.model_dump(exclude_unset=True)
        async with transactional(self.session):
            l = await self.listings.get_for_update(listing_id)
            assert_owner_listing(user, l)
            assert l is not None
            if l.status not in EDITABLE:
                raise ConflictError(f"A {l.status.value} listing cannot be edited")
            if l.status != L.DRAFT and {"crop_name", "crop_category"} & changes.keys():
                raise ConflictError("Crop name and category cannot change after the listing has been submitted")
            if "quantity_kg" in changes and changes["quantity_kg"] < l.reserved_kg:
                raise ConflictError(f"Quantity cannot be lower than the {l.reserved_kg} kg already reserved")
            before = listing_state(l)
            if "base_price" in changes:
                changes["base_price_paise"] = rupees_to_paise(changes.pop("base_price"))
            for k, v in changes.items():
                setattr(l, k, v)
            after = listing_state(l)
            if after != before:
                diff = {k: v for k, v in after.items() if before[k] != v}
                self.audit.record(action="listing.updated", entity_type="listing", entity_id=l.id,
                                  actor=Actor(user.id, user.role), ip=ctx.ip,
                                  previous_state={k: before[k] for k in diff}, new_state=diff)
        return await self._reload(listing_id)

    async def submit(self, user: User, listing_id: uuid.UUID, ctx: RequestContext) -> Listing:
        listing, _ = await self.submit_with_execution(user, listing_id, ctx)
        return listing

    async def submit_with_execution(self, user: User, listing_id: uuid.UUID, ctx: RequestContext) -> tuple[Listing, uuid.UUID]:
        """DRAFT/REVIEW_REQUIRED -> ANALYZING and creates the Crop Grading Agent execution (its id is the jobId)."""
        async with transactional(self.session):
            l = await self.listings.get_for_update(listing_id)
            assert_owner_listing(user, l)
            assert l is not None
            if l.status not in {L.DRAFT, L.REVIEW_REQUIRED}:
                assert_transition(LISTING_TRANSITIONS, l.status, L.ANALYZING)  # raises 409 with a clear message
            if await self.images.count_for_listing(l.id) == 0:
                raise ConflictError("Add at least one photo before submitting for grading")
            prev = l.status
            assert_transition(LISTING_TRANSITIONS, l.status, L.ANALYZING)
            l.status = L.ANALYZING
            execution, _ = await AgentExecutionService(self.session).queue(
                AgentName.CROP_GRADING, "listing.submitted", entity_type="listing", entity_id=l.id)
            execution_id = execution.id
            self.audit.record(action="listing.submitted", entity_type="listing", entity_id=l.id,
                              actor=Actor(user.id, user.role), ip=ctx.ip,
                              previous_state={"status": prev.value}, new_state={"status": L.ANALYZING.value})
        if self.enqueue_grading:  # only AFTER commit so the worker never sees uncommitted state
            try:
                await self.enqueue_grading(listing_id, execution_id)
            except Exception as exc:  # noqa: BLE001  (queue outage must not fail the request)
                # Listing stays ANALYZING; the stuck-listing sweeper (Stage 17) re-enqueues it.
                log.error("grading_enqueue_failed", listing_id=str(listing_id), error=str(exc))
        return await self._reload(listing_id), execution_id

    async def archive(self, user: User, listing_id: uuid.UUID, ctx: RequestContext) -> Listing:
        async with transactional(self.session):
            l = await self.listings.get_for_update(listing_id)
            assert_owner_listing(user, l, allow_admin=True)
            assert l is not None
            if l.reserved_kg > 0:
                raise ConflictError("Listing has active reservations and cannot be archived yet")
            prev = l.status
            assert_transition(LISTING_TRANSITIONS, l.status, L.ARCHIVED)
            l.status = L.ARCHIVED
            self.audit.record(action="listing.archived", entity_type="listing", entity_id=l.id,
                              actor=Actor(user.id, user.role), ip=ctx.ip,
                              previous_state={"status": prev.value}, new_state={"status": L.ARCHIVED.value})
        return await self._reload(listing_id)

    async def browse(self, user: User, f: ListingFilters, cursor: str | None, limit: int) -> ListingPage:
        """Marketplace browse: only ACTIVE listings (admins may filter by status via f.statuses)."""
        if user.role != UserRole.ADMIN or not f.statuses:
            f.statuses = [L.ACTIVE]
        return await self._page(f, cursor, limit)

    async def mine(self, user: User, f: ListingFilters, cursor: str | None, limit: int) -> ListingPage:
        f.farmer_id = user.id
        return await self._page(f, cursor, limit)

    async def _page(self, f: ListingFilters, cursor: str | None, limit: int) -> ListingPage:
        rows = await self.listings.search(f, decode_cursor(cursor) if cursor else None, limit)
        more = len(rows) > limit
        rows = rows[:limit]
        nxt = encode_cursor(rows[-1].created_at, rows[-1].id) if more else None
        return ListingPage(items=[await self.to_out(r) for r in rows], next_cursor=nxt)


_ = NotFoundError
