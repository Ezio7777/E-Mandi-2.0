import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.config import Settings
from app.core.dependencies import CurrentUser, RequestContextDep, SessionDep, SettingsDep, get_storage, require_roles
from app.integrations.aws.s3 import ObjectStorage
from app.models.enums import UserRole
from app.schemas.common import Envelope
from app.schemas.grading import GradingResultOut, ReviewQueueItem, ReviewRequest
from app.schemas.listing import ListingOut
from app.services.grading import GradingService, build_graders
from app.services.listing import ListingService

router = APIRouter(prefix="/grading", tags=["grading"])
Admin = Depends(require_roles(UserRole.ADMIN))


def get_grading_service(session: SessionDep, settings: SettingsDep,
                        storage: Annotated[ObjectStorage, Depends(get_storage)]) -> GradingService:
    return GradingService(session, settings, storage, build_graders(settings))


Svc = Annotated[GradingService, Depends(get_grading_service)]
_ = Settings


@router.get("/listings/{listing_id}", response_model=Envelope[GradingResultOut])
async def latest_result(listing_id: uuid.UUID, user: CurrentUser, svc: Svc):
    return Envelope(data=GradingResultOut.model_validate(await svc.result_for(user, listing_id)))


@router.get("/reviews", response_model=Envelope[list[ReviewQueueItem]], dependencies=[Admin])
async def review_queue(svc: Svc):
    return Envelope(data=await svc.review_queue())


@router.post("/listings/{listing_id}/review", response_model=Envelope[ListingOut], dependencies=[Admin])
async def review(listing_id: uuid.UUID, body: ReviewRequest, admin: CurrentUser, svc: Svc, ctx: RequestContextDep):
    listing = await svc.review_listing(admin, listing_id, body, ctx)
    return Envelope(data=await ListingService(svc.session).to_out(listing))


# ---------------------------------------------------------------------------------------------
# Frontend-contract endpoints (Stage 10): POST /grading -> {jobId}; job status carries the contract result
# ---------------------------------------------------------------------------------------------
from fastapi import status as http_status  # noqa: E402

from app.api.routes.listings import get_listing_service  # noqa: E402
from app.api.routes.pricing import latest_pricing, result_out  # noqa: E402
from app.models.enums import AgentName  # noqa: E402
from app.schemas.grading import GradingContractOut, GradingJobOut, GradingRequest  # noqa: E402
from app.schemas.pricing import JobAccepted  # noqa: E402
from app.services.agent_jobs import get_job_for_user, job_out  # noqa: E402


def contract_result(r) -> GradingContractOut:  # noqa: ANN001
    return GradingContractOut(grade=r.grade, confidence=r.confidence, defect_percent=r.defect_percentage,
                              explanation=r.reason, issues=list(r.issues), provider=r.provider.value, graded_at=r.created_at,
                              manual_review_recommended=r.requires_review, fallback_used=r.fallback_used, from_cache=r.from_cache)


@router.post("", response_model=Envelope[JobAccepted], status_code=http_status.HTTP_202_ACCEPTED,
             dependencies=[Depends(require_roles(UserRole.FARMER))])
async def start_grading(body: GradingRequest, user: CurrentUser, ctx: RequestContextDep,
                        listings: Annotated[ListingService, Depends(get_listing_service)]):
    """Same as submitting the listing: moves it to ANALYZING and queues the Crop Grading Agent."""
    _, job_id = await listings.submit_with_execution(user, body.listing_id, ctx)
    return Envelope(data=JobAccepted(job_id=str(job_id)))


@router.get("/jobs/{job_id}", response_model=Envelope[GradingJobOut])
async def grading_job(job_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    ex = await get_job_for_user(session, user, job_id, AgentName.CROP_GRADING)
    data = job_out(ex)
    if ex.related_entity_id and ex.status.value in {"COMPLETED", "REVIEW_REQUIRED"}:
        lid = uuid.UUID(ex.related_entity_id)
        res = await GradingService(session, None, None, []).latest_result(lid)  # type: ignore[arg-type]
        if res is not None:
            data["result"] = contract_result(res)
            pr = await latest_pricing(session, lid)
            data["pricing"] = result_out(pr) if pr else None
    return Envelope(data=GradingJobOut(**data))
