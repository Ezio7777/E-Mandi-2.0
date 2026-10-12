import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import CurrentUser, RequestContextDep, SessionDep, get_job_queue, require_roles
from app.core.rate_limit import rate_limit
from app.models.enums import UserRole
from app.schemas.common import Envelope
from app.schemas.requirement import RequirementCreate, RequirementOut
from app.services.requirement import RequirementService, to_out
from app.workers.queue import JobQueue

router = APIRouter(prefix="/requirements", tags=["requirements"])
Buyer = Depends(require_roles(UserRole.BUYER))


def get_requirement_service(session: SessionDep, queue: Annotated[JobQueue, Depends(get_job_queue)]) -> RequirementService:
    return RequirementService(session, queue)


Svc = Annotated[RequirementService, Depends(get_requirement_service)]


@router.post("", response_model=Envelope[RequirementOut], status_code=201, dependencies=[Buyer])
async def create_requirement(body: RequirementCreate, user: CurrentUser, svc: Svc, ctx: RequestContextDep):
    r, job_id = await svc.create(user, body, ctx)
    return Envelope(data=to_out(r, job_id))


@router.get("", response_model=Envelope[list[RequirementOut]], dependencies=[Buyer])
async def my_requirements(user: CurrentUser, svc: Svc):
    return Envelope(data=[to_out(r) for r in await svc.repo.list_for_buyer(user.id)])


@router.get("/{requirement_id}", response_model=Envelope[RequirementOut])
async def get_requirement(requirement_id: uuid.UUID, user: CurrentUser, svc: Svc):
    return Envelope(data=to_out(await svc.get(user, requirement_id)))


@router.post("/{requirement_id}/rematch", response_model=Envelope[RequirementOut], status_code=202,
             dependencies=[Buyer, Depends(rate_limit("rematch", 10, 60, per_user=True))])
async def rematch(requirement_id: uuid.UUID, user: CurrentUser, svc: Svc):
    r, job_id = await svc.rematch(user, requirement_id)
    return Envelope(data=to_out(r, job_id))


@router.post("/{requirement_id}/cancel", response_model=Envelope[RequirementOut], dependencies=[Buyer])
async def cancel(requirement_id: uuid.UUID, user: CurrentUser, svc: Svc, ctx: RequestContextDep):
    return Envelope(data=to_out(await svc.cancel(user, requirement_id, ctx)))
