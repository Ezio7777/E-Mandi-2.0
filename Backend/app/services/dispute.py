"""Disputes. Parties (buyer/farmer) raise and add evidence; ADMINS decide. Every step is audited and notified.

- One dispute per order (lifetime). Raising moves the order to DISPUTED under the order lock.
- Resolution is always a human admin decision (route is also blocked for demo sessions). Outcomes:
    SELLER_FAVOURED -> dispute RESOLVED, order DISPUTED -> COMPLETED
    BUYER_REFUND    -> dispute REFUND_REQUIRED; the admin then issues the refund (Stage 13 flow) which auto-resolves the
                       dispute (and moves the order to REFUNDED) when the payment is fully refunded.
- Lock order is order -> dispute (matches PaymentService: order -> payment -> dispute), so flows never deadlock.
"""
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import transactional
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.models.dispute import Dispute
from app.models.enums import DisputeStatus, NotificationType, OrderStatus, PaymentStatus, RefundStatus, UserRole
from app.models.order import Order
from app.models.user import User
from app.repositories.dispute import DisputeRepository
from app.repositories.payment import PaymentRepository
from app.schemas.dispute import DisputeCreate, DisputeOut, DisputePage, PartyRef, TimelineEntry
from app.services.audit import Actor, AuditService, RequestContext
from app.services.notification import NotificationService
from app.services.order import OrderService
from app.services.transitions import DISPUTE_TRANSITIONS, assert_transition
from app.utils.pagination import decode_cursor, encode_cursor
from app.utils.time import utcnow

DISPUTABLE = {OrderStatus.PAID, OrderStatus.CONFIRMED, OrderStatus.IN_FULFILLMENT, OrderStatus.COMPLETED}
OPEN_STATES = {DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW, DisputeStatus.EVIDENCE_REQUESTED}
PAID_STATES = [PaymentStatus.SUCCESS, PaymentStatus.REFUND_REQUESTED]


def _entry(kind: str, user: User, note: str) -> dict[str, Any]:
    return {"kind": kind, "by": str(user.id), "name": user.full_name, "role": user.role.value, "note": note, "at": utcnow().isoformat()}


class DisputeService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session, self.settings = session, settings
        self.disputes, self.orders = DisputeRepository(session), OrderService(session, settings)
        self.order_repo, self.payments = self.orders.orders, PaymentRepository(session)
        self.audit, self.notify = AuditService(session), NotificationService(session)

    # ---------------------------------------------------------------- reads
    async def _out(self, d: Dispute, o: Order) -> DisputeOut:
        raiser = await self.session.get(User, d.raised_by)
        return DisputeOut(
            id=d.id, order_id=d.order_id, order_status=o.status, raised_by=PartyRef(id=raiser.id, name=raiser.full_name, role=raiser.role),  # type: ignore[union-attr]
            category=d.category, description=d.description, status=d.status, resolution=d.resolution,
            timeline=[TimelineEntry(kind=e["kind"], by=e["by"], name=e["name"], role=e["role"], note=e["note"], at=e["at"]) for e in d.evidence],
            refund_required=d.status == DisputeStatus.REFUND_REQUIRED, resolved_at=d.resolved_at, created_at=d.created_at, updated_at=d.updated_at)

    async def _visible(self, user: User, dispute_id: uuid.UUID) -> tuple[Dispute, Order]:
        d = await self.disputes.get(dispute_id)
        o = await self.order_repo.get(d.order_id) if d else None
        if d is None or o is None or not (user.role == UserRole.ADMIN or user.id in (o.buyer_id, o.farmer_id)):
            raise NotFoundError("Dispute not found")  # no existence leak
        return d, o

    async def view(self, user: User, dispute_id: uuid.UUID) -> DisputeOut:
        return await self._out(*(await self._visible(user, dispute_id)))

    async def list_for_user(self, user: User, status: DisputeStatus | None, cursor: str | None, limit: int) -> DisputePage:
        rows = await self.disputes.list_for(None if user.role == UserRole.ADMIN else user.id, status,
                                            decode_cursor(cursor) if cursor else None, limit)
        more, rows = len(rows) > limit, rows[:limit]
        items = [await self._out(d, await self.order_repo.get(d.order_id)) for d in rows]  # type: ignore[arg-type]
        return DisputePage(items=items, next_cursor=encode_cursor(rows[-1].created_at, rows[-1].id) if more else None)

    # ---------------------------------------------------------------- party actions
    async def create(self, user: User, data: DisputeCreate, ctx: RequestContext) -> DisputeOut:
        async with transactional(self.session):
            o = await self.order_repo.get_for_update(data.order_id)
            if o is None or user.id not in (o.buyer_id, o.farmer_id):
                raise NotFoundError("Order not found")
            if await self.disputes.for_order(o.id):
                raise ConflictError("This order already has a dispute")
            if o.status not in DISPUTABLE:
                raise ConflictError(f"A dispute cannot be raised on a {o.status.value} order")
            if o.status == OrderStatus.COMPLETED and utcnow() - o.updated_at > timedelta(days=self.settings.DISPUTE_WINDOW_DAYS):
                raise ConflictError(f"The {self.settings.DISPUTE_WINDOW_DAYS}-day dispute window for completed orders has closed")
            d = Dispute(order_id=o.id, raised_by=user.id, category=data.category, description=data.description,
                        status=DisputeStatus.OPEN, evidence=[_entry("opened", user, data.description)])
            self.session.add(d)
            await self.session.flush()
            self.orders._transition(o, OrderStatus.DISPUTED, Actor(user.id, user.role), ctx.ip, dispute_id=str(d.id), category=data.category)
            self.audit.record(action="dispute.created", entity_type="dispute", entity_id=d.id, actor=Actor(user.id, user.role), ip=ctx.ip,
                              metadata={"order_id": str(o.id), "category": data.category}, new_state={"status": "OPEN"})
            other = o.farmer_id if user.id == o.buyer_id else o.buyer_id
            self.notify.add(other, NotificationType.DISPUTE_UPDATED, "A dispute was raised on your order",
                            f"A {data.category.replace('_', ' ').lower()} dispute was opened on order {str(o.id)[:8]}.", {"dispute_id": str(d.id), "order_id": str(o.id)})
            await self.notify.notify_admins(NotificationType.DISPUTE_UPDATED, "New dispute to review",
                                            f"{data.category.replace('_', ' ').title()} dispute on order {str(o.id)[:8]}.", {"dispute_id": str(d.id)})
            did = d.id
        return await self.view(user, did)

    async def add_evidence(self, user: User, dispute_id: uuid.UUID, note: str, ctx: RequestContext) -> DisputeOut:
        async with transactional(self.session):
            d0, _ = await self._visible(user, dispute_id)
            o = await self.order_repo.get_for_update(d0.order_id)
            if user.id not in (o.buyer_id, o.farmer_id):  # type: ignore[union-attr]
                raise ForbiddenError("Only the buyer or farmer on the order can add evidence")
            d = await self.disputes.get_for_update(dispute_id)
            if d.status not in OPEN_STATES:  # type: ignore[union-attr]
                raise ConflictError(f"Evidence cannot be added to a {d.status.value} dispute")  # type: ignore[union-attr]
            d.evidence = [*d.evidence, _entry("evidence", user, note)]  # type: ignore[union-attr]
            prev = d.status  # type: ignore[union-attr]
            if prev == DisputeStatus.EVIDENCE_REQUESTED:
                d.status = DisputeStatus.UNDER_REVIEW  # type: ignore[union-attr]
            self.audit.record(action="dispute.evidence_added", entity_type="dispute", entity_id=dispute_id, actor=Actor(user.id, user.role),
                              ip=ctx.ip, previous_state={"status": prev.value}, new_state={"status": d.status.value})  # type: ignore[union-attr]
            await self.notify.notify_admins(NotificationType.DISPUTE_UPDATED, "New dispute evidence",
                                            f"{user.full_name} added evidence to dispute {str(dispute_id)[:8]}.", {"dispute_id": str(dispute_id)})
        return await self.view(user, dispute_id)

    # ---------------------------------------------------------------- admin actions
    async def _admin_locked(self, admin: User, dispute_id: uuid.UUID) -> tuple[Dispute, Order]:
        if admin.role != UserRole.ADMIN:
            raise NotFoundError("Dispute not found")
        d0 = await self.disputes.get(dispute_id)
        if d0 is None:
            raise NotFoundError("Dispute not found")
        o = await self.order_repo.get_for_update(d0.order_id)  # order first ...
        d = await self.disputes.get_for_update(dispute_id)     # ... then dispute
        return d, o  # type: ignore[return-value]

    def _parties(self, o: Order, which: str = "both") -> list[uuid.UUID]:
        return {"buyer": [o.buyer_id], "farmer": [o.farmer_id]}.get(which, [o.buyer_id, o.farmer_id])

    def _set(self, d: Dispute, target: DisputeStatus) -> DisputeStatus:
        prev = d.status
        assert_transition(DISPUTE_TRANSITIONS, prev, target)
        d.status = target
        return prev

    async def start_review(self, admin: User, dispute_id: uuid.UUID, ctx: RequestContext) -> DisputeOut:
        async with transactional(self.session):
            d, o = await self._admin_locked(admin, dispute_id)
            prev = self._set(d, DisputeStatus.UNDER_REVIEW)
            self.audit.record(action="dispute.review_started", entity_type="dispute", entity_id=d.id, actor=Actor(admin.id, admin.role), ip=ctx.ip,
                              previous_state={"status": prev.value}, new_state={"status": "UNDER_REVIEW"})
            for uid in self._parties(o):
                self.notify.add(uid, NotificationType.DISPUTE_UPDATED, "Dispute under review", f"An admin is reviewing dispute {str(d.id)[:8]}.", {"dispute_id": str(d.id)})
        return await self.view(admin, dispute_id)

    async def request_evidence(self, admin: User, dispute_id: uuid.UUID, from_party: str, message: str, ctx: RequestContext) -> DisputeOut:
        async with transactional(self.session):
            d, o = await self._admin_locked(admin, dispute_id)
            prev = self._set(d, DisputeStatus.EVIDENCE_REQUESTED)
            d.evidence = [*d.evidence, _entry("admin_request", admin, f"[{from_party}] {message}")]
            self.audit.record(action="dispute.evidence_requested", entity_type="dispute", entity_id=d.id, actor=Actor(admin.id, admin.role), ip=ctx.ip,
                              metadata={"from": from_party}, previous_state={"status": prev.value}, new_state={"status": "EVIDENCE_REQUESTED"})
            for uid in self._parties(o, from_party):
                self.notify.add(uid, NotificationType.DISPUTE_UPDATED, "Evidence requested", f"An admin asked for more information on dispute {str(d.id)[:8]}.",
                                {"dispute_id": str(d.id)})
        return await self.view(admin, dispute_id)

    async def resolve(self, admin: User, dispute_id: uuid.UUID, outcome: str, resolution: str, ctx: RequestContext) -> DisputeOut:
        async with transactional(self.session):
            d, o = await self._admin_locked(admin, dispute_id)
            if d.status not in OPEN_STATES:
                raise ConflictError(f"A {d.status.value} dispute cannot be resolved")
            payments = await self.payments.for_order(o.id)
            if outcome == "SELLER_FAVOURED":
                for p in payments:  # refuse to close in the seller's favour while money is mid-refund
                    if await self.payments.refund_total(p.id, [RefundStatus.REQUESTED, RefundStatus.PROCESSING]):
                        raise ConflictError("A refund is in progress for this order")
                prev = self._set(d, DisputeStatus.RESOLVED)
                d.resolved_at = utcnow()
                self.orders._transition(o, OrderStatus.COMPLETED, Actor(admin.id, admin.role), ctx.ip, dispute_id=str(d.id), outcome=outcome)
            else:
                if not any(p.status in PAID_STATES for p in payments):
                    raise ConflictError("There is no successful payment to refund for this order")
                prev = self._set(d, DisputeStatus.REFUND_REQUIRED)
            d.resolution, d.resolved_by = resolution, admin.id
            self.audit.record(action="dispute.resolved" if outcome == "SELLER_FAVOURED" else "dispute.refund_required", entity_type="dispute",
                              entity_id=d.id, actor=Actor(admin.id, admin.role), ip=ctx.ip, metadata={"outcome": outcome, "resolution": resolution},
                              previous_state={"status": prev.value}, new_state={"status": d.status.value})
            for uid in self._parties(o):
                self.notify.add(uid, NotificationType.DISPUTE_UPDATED, "Dispute decision",
                                "The dispute was decided in the seller's favour." if outcome == "SELLER_FAVOURED"
                                else "The dispute was decided in the buyer's favour; a refund will be issued.", {"dispute_id": str(d.id), "outcome": outcome})
        return await self.view(admin, dispute_id)

    async def refund_target(self, admin: User, dispute_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
        """Validates a refund can be issued for this dispute and returns (payment_id, dispute_id)."""
        d, o = await self._visible(admin, dispute_id)
        if admin.role != UserRole.ADMIN:
            raise NotFoundError("Dispute not found")
        if d.status != DisputeStatus.REFUND_REQUIRED:
            raise ConflictError("Decide the dispute in the buyer's favour (BUYER_REFUND) before issuing a refund")
        paid = [p for p in await self.payments.for_order(o.id) if p.status in PAID_STATES]
        if not paid:
            raise ConflictError("There is no refundable payment for this order")
        return paid[0].id, d.id

    async def close(self, admin: User, dispute_id: uuid.UUID, ctx: RequestContext) -> DisputeOut:
        async with transactional(self.session):
            d, _ = await self._admin_locked(admin, dispute_id)
            prev = self._set(d, DisputeStatus.CLOSED)
            self.audit.record(action="dispute.closed", entity_type="dispute", entity_id=d.id, actor=Actor(admin.id, admin.role), ip=ctx.ip,
                              previous_state={"status": prev.value}, new_state={"status": "CLOSED"})
        return await self.view(admin, dispute_id)
