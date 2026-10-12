import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.runtime import dispatch
from app.core.dependencies import CurrentUser, SessionDep, get_job_queue, require_roles
from app.core.errors import ConflictError, NotFoundError
from app.core.rate_limit import rate_limit
from sqlalchemy import select
from app.models.enums import AgentName, UserRole
from app.models.enums import ListingStatus as L
from app.models.pricing_result import PricingResult
from app.repositories.listing import ListingRepository
from app.schemas.common import Envelope
from app.schemas.pricing import JobAccepted, JobStatusOut, PricingResultOut
from app.services.access import assert_owner_listing
from app.services.agent_jobs import get_job_for_user, job_out
from app.workers.queue import JobQueue

router = APIRouter(prefix="/pricing", tags=["pricing"])


def result_out(r: PricingResult) -> PricingResultOut:
    from app.utils.money import paise_to_rupees as rs
    from app.schemas.pricing import PriceFactorOut
    return PricingResultOut(
        pricing_id=str(r.id), listing_id=str(r.listing_id), suggested=rs(r.suggested_paise), range_min=rs(r.range_min_paise),
        range_max=rs(r.range_max_paise), reference_price=rs(r.reference_paise), trend=r.trend,  # type: ignore[arg-type]
        explanation=r.explanation, source=r.source, scope=r.scope, data_points=r.data_points, is_sample=r.is_sample,  # type: ignore[arg-type]
        factors=[PriceFactorOut(name=f["name"], effect_pct=f["effectPct"], detail=f["detail"]) for f in r.factors],
        explanation_provider=r.explanation_provider,  # type: ignore[arg-type]
        created_at=r.created_at.isoformat())


async def latest_pricing(session, listing_id: uuid.UUID) -> PricingResult | None:  # noqa: ANN001
    return await session.scalar(select(PricingResult).where(PricingResult.listing_id == listing_id)
                                .order_by(PricingResult.created_at.desc()).limit(1))


@router.get("/listings/{listing_id}", response_model=Envelope[PricingResultOut])
async def get_pricing(listing_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    assert_owner_listing(user, await ListingRepository(session).get(listing_id), allow_admin=True)
    r = await latest_pricing(session, listing_id)
    if r is None:
        raise NotFoundError("No price suggestion yet")
    return Envelope(data=result_out(r))


@router.post("/listings/{listing_id}/refresh", response_model=Envelope[JobAccepted], status_code=202,
             dependencies=[Depends(rate_limit("pricing_refresh", 10, 60, per_user=True))])
async def refresh_pricing(listing_id: uuid.UUID, user: CurrentUser, session: SessionDep,
                          queue: Annotated[JobQueue, Depends(get_job_queue)],
                          _: Annotated[object, Depends(require_roles(UserRole.FARMER))] = None):
    l = assert_owner_listing(user, await ListingRepository(session).get(listing_id))
    if l.status in {L.ARCHIVED, L.SOLD}:
        raise ConflictError(f"A {l.status.value} listing cannot be priced")
    job_id = await dispatch(session, queue, agent=AgentName.SMART_PRICING, job_name="price_listing_job",
                            trigger_type="pricing.refresh_requested", entity_type="listing", entity_id=l.id,
                            job_args=(str(l.id), None))
    return Envelope(data=JobAccepted(job_id=str(job_id)))


@router.get("/jobs/{job_id}", response_model=Envelope[JobStatusOut])
async def pricing_job(job_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    return Envelope(data=JobStatusOut(**job_out(await get_job_for_user(session, user, job_id, AgentName.SMART_PRICING))))
