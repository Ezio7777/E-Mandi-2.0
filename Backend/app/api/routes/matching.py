"""Matching contract endpoints: [{listingId, score, reasons[{factor, matched, detail}]}] plus job status."""
import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select

from app.api.routes.requirements import Svc, get_requirement_service  # noqa: F401
from app.core.dependencies import CurrentUser, RequestContextDep, SessionDep, require_roles
from app.models.enums import AgentName, UserRole
from app.models.listing import Listing
from app.models.match import Match
from app.repositories.match import MatchRepository
from app.schemas.common import Envelope
from app.schemas.matching import MatchingJobOut, MatchListingSummary, MatchOut, MatchSetOut
from app.services.agent_jobs import get_job_for_user, job_out
from app.utils.money import paise_to_rupees

router = APIRouter(prefix="/matching", tags=["matching"])


def match_out(m: Match, l: Listing) -> MatchOut:
    return MatchOut(
        match_id=m.id, listing_id=m.listing_id, score=round(m.score * 100, 1), reasons=m.reasons,
        grade_score=m.grade_score, quantity_score=m.quantity_score, location_score=m.location_score,
        price_score=m.price_score, availability_score=m.availability_score, distance_km=m.distance_km, rank=m.rank,
        status=m.status, created_at=m.created_at,
        listing=MatchListingSummary(crop_name=l.crop_name, farmer_name=l.farmer.full_name,
                                    price_per_kg=paise_to_rupees(l.base_price_paise), available_kg=l.available_kg,
                                    grade=l.ai_grade, location=l.location))


@router.get("/requirements/{requirement_id}", response_model=Envelope[MatchSetOut])
async def matches_for_requirement(requirement_id: uuid.UUID, user: CurrentUser, session: SessionDep, svc: Svc):
    r = await svc.get(user, requirement_id)  # owner or admin, else 404
    rows = await MatchRepository(session).for_requirement(r.id)
    out, covered = [], Decimal(0)
    for m in rows:
        l = await session.get(Listing, m.listing_id)
        if l is None:
            continue
        out.append(match_out(m, l))
        covered += Decimal(m.breakdown["listing"]["available_kg"])  # stock as of match time (reproducible)
    return Envelope(data=MatchSetOut(requirement_id=r.id, requested_kg=r.quantity_kg, covered_kg=covered,
                                     fully_covered=covered >= r.quantity_kg, matches=out))


@router.post("/{match_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT,
             dependencies=[Depends(require_roles(UserRole.BUYER))])
async def dismiss(match_id: uuid.UUID, user: CurrentUser, svc: Svc, ctx: RequestContextDep) -> None:
    await svc.dismiss_match(user, match_id, ctx)


@router.get("/jobs/{job_id}", response_model=Envelope[MatchingJobOut])
async def matching_job(job_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    ex = await get_job_for_user(session, user, job_id, AgentName.BUYER_MATCHING)
    data = job_out(ex)
    data["requirement_id"] = ex.related_entity_id
    data["match_count"] = await session.scalar(select(func.count()).select_from(Match).where(
        Match.execution_id == ex.id)) if ex.related_entity_id else None
    return Envelope(data=MatchingJobOut(**data))


_ = Annotated
