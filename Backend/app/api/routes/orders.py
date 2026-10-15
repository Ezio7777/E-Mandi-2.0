import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response

from app.agents.fraud_risk.events import emit_risk_event
from app.core.dependencies import CurrentUser, RequestContextDep, SessionDep, SettingsDep, get_job_queue, require_roles
from app.core.rate_limit import rate_limit
from app.models.enums import OrderStatus, UserRole
from app.schemas.common import Envelope
from app.schemas.order import CancelRequest, OrderCreate, OrderOut, OrderPage
from app.services.order import OrderService, to_out
from app.workers.queue import JobQueue

router = APIRouter(prefix="/orders", tags=["orders"])
Buyer = Depends(require_roles(UserRole.BUYER))
Farmer = Depends(require_roles(UserRole.FARMER))
IdemKey = Annotated[str | None, Header(alias="Idempotency-Key", min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_\-:.]+$")]


def get_order_service(session: SessionDep, settings: SettingsDep) -> OrderService:
    return OrderService(session, settings)


Svc = Annotated[OrderService, Depends(get_order_service)]


@router.post("", response_model=Envelope[OrderOut], status_code=201,
             dependencies=[Buyer, Depends(rate_limit("order_create", 20, 60, per_user=True))])
async def create_order(body: OrderCreate, user: CurrentUser, svc: Svc, ctx: RequestContextDep, response: Response, session: SessionDep,
                       queue: Annotated[JobQueue, Depends(get_job_queue)], idempotency_key: IdemKey = None):
    """Send an Idempotency-Key header (any unique string per checkout attempt) so retries/double-clicks never double-order."""
    order, created = await svc.create(user, body, idempotency_key, ctx)
    if not created:
        response.status_code = 200
        response.headers["Idempotency-Replayed"] = "true"
    else:
        await emit_risk_event(session, queue, "order.created", order.id, idempotency_key=f"risk:order.created:{order.id}")
    return Envelope(data=to_out(order))


@router.get("", response_model=Envelope[OrderPage])
async def list_orders(user: CurrentUser, svc: Svc, status: OrderStatus | None = None,
                      cursor: str | None = Query(None, max_length=300), limit: int = Query(20, ge=1, le=50)):
    return Envelope(data=await svc.list(user, status, cursor, limit))


@router.get("/{order_id}", response_model=Envelope[OrderOut])
async def get_order(order_id: uuid.UUID, user: CurrentUser, svc: Svc):
    return Envelope(data=to_out(await svc.get(user, order_id)))


@router.post("/{order_id}/cancel", response_model=Envelope[OrderOut],
             dependencies=[Depends(require_roles(UserRole.BUYER, UserRole.FARMER))])
async def cancel_order(order_id: uuid.UUID, user: CurrentUser, svc: Svc, ctx: RequestContextDep, body: CancelRequest | None = None):
    return Envelope(data=to_out(await svc.cancel(user, order_id, body.reason if body else None, ctx)))


@router.post("/{order_id}/confirm", response_model=Envelope[OrderOut], dependencies=[Farmer])
async def confirm_order(order_id: uuid.UUID, user: CurrentUser, svc: Svc, ctx: RequestContextDep):
    return Envelope(data=to_out(await svc.confirm(user, order_id, ctx)))


@router.post("/{order_id}/start-fulfillment", response_model=Envelope[OrderOut], dependencies=[Farmer])
async def start_fulfillment(order_id: uuid.UUID, user: CurrentUser, svc: Svc, ctx: RequestContextDep):
    return Envelope(data=to_out(await svc.start_fulfillment(user, order_id, ctx)))


@router.post("/{order_id}/complete", response_model=Envelope[OrderOut], dependencies=[Buyer])
async def complete_order(order_id: uuid.UUID, user: CurrentUser, svc: Svc, ctx: RequestContextDep):
    return Envelope(data=to_out(await svc.complete(user, order_id, ctx)))
