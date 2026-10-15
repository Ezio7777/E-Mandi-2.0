import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.routes.payments import get_payment_service
from app.core.dependencies import CurrentUser, RequestContextDep, SessionDep, SettingsDep, forbid_demo, require_roles
from app.core.rate_limit import rate_limit
from app.models.enums import DisputeStatus, UserRole
from app.schemas.common import Envelope
from app.schemas.dispute import (
    DisputeCreate,
    DisputeOut,
    DisputePage,
    DisputeRefundIn,
    EvidenceIn,
    EvidenceRequestIn,
    ResolveIn,
)
from app.services.dispute import DisputeService
from app.services.payment import PaymentService
from app.utils.money import rupees_to_paise

router = APIRouter(prefix="/disputes", tags=["disputes"])
Admin = Depends(require_roles(UserRole.ADMIN))
Party = Depends(require_roles(UserRole.BUYER, UserRole.FARMER))


def get_dispute_service(session: SessionDep, settings: SettingsDep) -> DisputeService:
    return DisputeService(session, settings)


Svc = Annotated[DisputeService, Depends(get_dispute_service)]


@router.post("", response_model=Envelope[DisputeOut], status_code=201,
             dependencies=[Party, Depends(rate_limit("dispute_create", 10, 3600, per_user=True))])
async def create_dispute(body: DisputeCreate, user: CurrentUser, svc: Svc, ctx: RequestContextDep):
    return Envelope(data=await svc.create(user, body, ctx))


@router.get("", response_model=Envelope[DisputePage])
async def list_disputes(user: CurrentUser, svc: Svc, status: DisputeStatus | None = None,
                        cursor: str | None = Query(None, max_length=300), limit: int = Query(20, ge=1, le=50)):
    return Envelope(data=await svc.list_for_user(user, status, cursor, limit))


@router.get("/{dispute_id}", response_model=Envelope[DisputeOut])
async def get_dispute(dispute_id: uuid.UUID, user: CurrentUser, svc: Svc):
    return Envelope(data=await svc.view(user, dispute_id))


@router.post("/{dispute_id}/evidence", response_model=Envelope[DisputeOut], dependencies=[Party])
async def add_evidence(dispute_id: uuid.UUID, body: EvidenceIn, user: CurrentUser, svc: Svc, ctx: RequestContextDep):
    return Envelope(data=await svc.add_evidence(user, dispute_id, body.note, ctx))


@router.post("/{dispute_id}/review", response_model=Envelope[DisputeOut], dependencies=[Admin])
async def start_review(dispute_id: uuid.UUID, admin: CurrentUser, svc: Svc, ctx: RequestContextDep):
    return Envelope(data=await svc.start_review(admin, dispute_id, ctx))


@router.post("/{dispute_id}/request-evidence", response_model=Envelope[DisputeOut], dependencies=[Admin])
async def request_evidence(dispute_id: uuid.UUID, body: EvidenceRequestIn, admin: CurrentUser, svc: Svc, ctx: RequestContextDep):
    return Envelope(data=await svc.request_evidence(admin, dispute_id, body.from_party, body.message, ctx))


@router.post("/{dispute_id}/resolve", response_model=Envelope[DisputeOut], dependencies=[Admin, Depends(forbid_demo)])
async def resolve(dispute_id: uuid.UUID, body: ResolveIn, admin: CurrentUser, svc: Svc, ctx: RequestContextDep):
    """Human decision (blocked for demo sessions: it changes order state / commits to a refund)."""
    return Envelope(data=await svc.resolve(admin, dispute_id, body.outcome, body.resolution, ctx))


@router.post("/{dispute_id}/refund", response_model=Envelope[DisputeOut], status_code=201, dependencies=[Admin, Depends(forbid_demo)])
async def refund(dispute_id: uuid.UUID, body: DisputeRefundIn, admin: CurrentUser, svc: Svc, payments: Annotated[PaymentService, Depends(get_payment_service)],
                 ctx: RequestContextDep):
    """Issues the refund for a REFUND_REQUIRED dispute through the payment flow; full refund auto-resolves the dispute."""
    payment_id, did = await svc.refund_target(admin, dispute_id)
    paise = rupees_to_paise(Decimal(str(body.amount))) if body.amount is not None else None
    await payments.request_refund(admin, payment_id, paise, body.reason or f"Dispute {str(did)[:8]} resolved in buyer's favour", ctx, dispute_id=did)
    return Envelope(data=await svc.view(admin, dispute_id))


@router.post("/{dispute_id}/close", response_model=Envelope[DisputeOut], dependencies=[Admin])
async def close(dispute_id: uuid.UUID, admin: CurrentUser, svc: Svc, ctx: RequestContextDep):
    return Envelope(data=await svc.close(admin, dispute_id, ctx))
