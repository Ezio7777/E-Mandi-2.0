import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.agents.fraud_risk.events import emit_risk_event
from app.core.dependencies import (
    CurrentUser, RequestContextDep, SessionDep, get_job_queue, get_url_resolver, require_roles,
)
from app.core.errors import DomainValidationError
from app.integrations.aws.image_url_resolver import ImageUrlResolver
from app.models.enums import CropCategory, Grade, ListingStatus, UserRole
from app.repositories.listing import ListingFilters
from app.schemas.common import Envelope
from app.workers.queue import JobQueue
from app.schemas.listing import ListingCreate, ListingOut, ListingPage, ListingUpdate
from app.services.listing import ListingService
from app.utils.money import rupees_to_paise

router = APIRouter(prefix="/listings", tags=["listings"])
Farmer = Depends(require_roles(UserRole.FARMER))


def get_listing_service(session: SessionDep, resolver: Annotated[ImageUrlResolver, Depends(get_url_resolver)],
                        queue: Annotated[JobQueue, Depends(get_job_queue)]) -> ListingService:
    async def enqueue(listing_id: uuid.UUID, execution_id: uuid.UUID) -> None:
        await queue.enqueue("grade_listing_job", str(listing_id), str(execution_id))

    return ListingService(session, resolver, enqueue)


Svc = Annotated[ListingService, Depends(get_listing_service)]


def _filters(crop: str | None, category: CropCategory | None, location: str | None, min_price: Decimal | None,
             max_price: Decimal | None, min_grade: Grade | None, min_quantity_kg: Decimal | None,
             status: ListingStatus | None) -> ListingFilters:
    try:
        return ListingFilters(
            statuses=[status] if status else [], crop=crop, category=category.value if category else None,
            location=location, min_price_paise=rupees_to_paise(min_price) if min_price is not None else None,
            max_price_paise=rupees_to_paise(max_price) if max_price is not None else None,
            min_grade=min_grade, min_available_kg=min_quantity_kg)
    except ValueError as exc:
        raise DomainValidationError(str(exc)) from exc


def _q(crop: str | None = Query(None, max_length=120), category: CropCategory | None = None,
       location: str | None = Query(None, max_length=200), min_price: Decimal | None = Query(None, ge=0),
       max_price: Decimal | None = Query(None, ge=0), min_grade: Grade | None = None,
       min_quantity_kg: Decimal | None = Query(None, ge=0), status: ListingStatus | None = None) -> ListingFilters:
    return _filters(crop, category, location, min_price, max_price, min_grade, min_quantity_kg, status)


Filters = Annotated[ListingFilters, Depends(_q)]
Cursor = Annotated[str | None, Query(max_length=300)]
Limit = Annotated[int, Query(ge=1, le=50)]


@router.post("", response_model=Envelope[ListingOut], status_code=201, dependencies=[Farmer])
async def create_listing(body: ListingCreate, user: CurrentUser, svc: Svc, ctx: RequestContextDep, session: SessionDep,
                         queue: Annotated[JobQueue, Depends(get_job_queue)]):
    listing = await svc.create(user, body, ctx)
    await emit_risk_event(session, queue, "listing.created", listing.id, idempotency_key=f"risk:listing.created:{listing.id}")
    return Envelope(data=await svc.to_out(listing))


@router.get("", response_model=Envelope[ListingPage])
async def browse(user: CurrentUser, svc: Svc, f: Filters, cursor: Cursor = None, limit: Limit = 20):
    return Envelope(data=await svc.browse(user, f, cursor, limit))


@router.get("/mine", response_model=Envelope[ListingPage], dependencies=[Farmer])
async def my_listings(user: CurrentUser, svc: Svc, f: Filters, cursor: Cursor = None, limit: Limit = 20):
    return Envelope(data=await svc.mine(user, f, cursor, limit))


@router.get("/{listing_id}", response_model=Envelope[ListingOut])
async def get_listing(listing_id: uuid.UUID, user: CurrentUser, svc: Svc):
    return Envelope(data=await svc.to_out(await svc.get(user, listing_id)))


@router.patch("/{listing_id}", response_model=Envelope[ListingOut], dependencies=[Farmer])
async def update_listing(listing_id: uuid.UUID, body: ListingUpdate, user: CurrentUser, svc: Svc,
                         ctx: RequestContextDep, session: SessionDep, queue: Annotated[JobQueue, Depends(get_job_queue)]):
    listing = await svc.update(user, listing_id, body, ctx)
    await emit_risk_event(session, queue, "listing.updated", listing.id)
    return Envelope(data=await svc.to_out(listing))


@router.post("/{listing_id}/submit", response_model=Envelope[ListingOut], dependencies=[Farmer])
async def submit_listing(listing_id: uuid.UUID, user: CurrentUser, svc: Svc, ctx: RequestContextDep, session: SessionDep,
                         queue: Annotated[JobQueue, Depends(get_job_queue)]):
    listing = await svc.submit(user, listing_id, ctx)
    await emit_risk_event(session, queue, "listing.submitted", listing.id, idempotency_key=f"risk:listing.submitted:{listing.id}")
    return Envelope(data=await svc.to_out(listing))


@router.post("/{listing_id}/archive", response_model=Envelope[ListingOut],
             dependencies=[Depends(require_roles(UserRole.FARMER, UserRole.ADMIN))])
async def archive_listing(listing_id: uuid.UUID, user: CurrentUser, svc: Svc, ctx: RequestContextDep):
    return Envelope(data=await svc.to_out(await svc.archive(user, listing_id, ctx)))
