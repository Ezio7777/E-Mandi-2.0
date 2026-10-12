import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response

from app.core.dependencies import (
    CurrentUser, RequestContextDep, SessionDep, SettingsDep, forbid_demo, get_job_queue, get_payment_provider, require_roles,
)
from app.core.errors import AppError, DomainValidationError
from app.core.rate_limit import rate_limit
from app.integrations.payments.base import PaymentProvider
from app.models.enums import UserRole
from app.schemas.common import Envelope
from app.schemas.payment import PaymentCreate, PaymentOut, RefundCreate, SimulateRequest, WebhookAck
from app.services.payment import PaymentService, to_out
from app.utils.money import rupees_to_paise
from app.workers.queue import JobQueue

router = APIRouter(prefix="/payments", tags=["payments"])
MAX_WEBHOOK_BYTES = 256 * 1024
# Idempotency-Key is REQUIRED for payment creation (retries/double clicks must never create two charges)
IdemKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_\-:.]+$")]


def get_payment_service(session: SessionDep, settings: SettingsDep, provider: Annotated[PaymentProvider, Depends(get_payment_provider)],
                        queue: Annotated[JobQueue, Depends(get_job_queue)]) -> PaymentService:
    svc = PaymentService(session, settings, provider)
    svc.risk_queue = queue
    return svc


Svc = Annotated[PaymentService, Depends(get_payment_service)]


@router.post("", response_model=Envelope[PaymentOut], status_code=201,
             dependencies=[Depends(require_roles(UserRole.BUYER)), Depends(rate_limit("payment_create", 10, 60, per_user=True))])
async def create_payment(body: PaymentCreate, user: CurrentUser, svc: Svc, ctx: RequestContextDep, response: Response, idempotency_key: IdemKey):
    out, created = await svc.create_payment(user, body.order_id, idempotency_key, ctx)
    if not created:
        response.status_code = 200
        response.headers["Idempotency-Replayed"] = "true"
    return Envelope(data=out)


@router.post("/webhook", response_model=WebhookAck, include_in_schema=True,
             dependencies=[Depends(rate_limit("payment_webhook", 600, 60))])
async def webhook(request: Request, svc: Svc, provider: Annotated[PaymentProvider, Depends(get_payment_provider)]):
    """Called by the payment provider. Authenticated ONLY by the HMAC signature over the raw body."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_WEBHOOK_BYTES:
        raise AppError("Payload too large")
    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BYTES:
        raise AppError("Payload too large")
    status = await svc.handle_webhook(raw, request.headers.get(provider.signature_header), request.headers.get(provider.event_id_header))
    return WebhookAck(status=status)


@router.get("/order/{order_id}", response_model=Envelope[list[PaymentOut]])
async def payments_for_order(order_id: uuid.UUID, user: CurrentUser, svc: Svc):
    return Envelope(data=await svc.for_order(user, order_id))


@router.get("/{payment_id}", response_model=Envelope[PaymentOut])
async def get_payment(payment_id: uuid.UUID, user: CurrentUser, svc: Svc):
    return Envelope(data=await svc.view(user, payment_id))


@router.post("/{payment_id}/simulate", response_model=Envelope[PaymentOut],
             dependencies=[Depends(require_roles(UserRole.BUYER)), Depends(rate_limit("payment_simulate", 20, 60, per_user=True))])
async def simulate(payment_id: uuid.UUID, body: SimulateRequest, user: CurrentUser, svc: Svc):
    """DEMO ONLY (mock provider + DEMO_MODE): runs a signed webhook through the production pipeline. 404 otherwise."""
    await svc.simulate(user, payment_id, body.outcome)
    return Envelope(data=await svc.view(user, payment_id))


@router.post("/{payment_id}/refunds", response_model=Envelope[PaymentOut], status_code=201,
             dependencies=[Depends(require_roles(UserRole.ADMIN)), Depends(forbid_demo)])
async def create_refund(payment_id: uuid.UUID, body: RefundCreate, admin: CurrentUser, svc: Svc, ctx: RequestContextDep):
    """Admin only; blocked for demo sessions (irreversible money movement)."""
    try:
        paise = rupees_to_paise(body.amount) if body.amount is not None else None
    except ValueError as exc:
        raise DomainValidationError(str(exc)) from exc
    await svc.request_refund(admin, payment_id, paise, body.reason, ctx)
    return Envelope(data=await svc.view(admin, payment_id))


_ = (Decimal, to_out)
