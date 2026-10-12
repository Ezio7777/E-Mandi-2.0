"""Payment lifecycle: a secure MARKETPLACE payment flow on a sandbox provider (not a regulated escrow).

Security properties
- The charged amount is ALWAYS order.total_amount_paise (computed server-side); clients cannot send an amount.
- Webhooks: HMAC verified on the RAW body BEFORE any database write; unset secret fails closed.
- Duplicate protection: UNIQUE(provider, provider_event_id) in payment_events + processed_at; unprocessed duplicates are
  re-applied (crash recovery), processed ones acknowledged without effect. Capture amount/currency must match exactly.
- Atomicity: payment SUCCESS + order PAID + inventory commit + event processed commit in ONE transaction.
- Lock order is always: order row, then payment row (matches OrderService), so flows never deadlock.
- Only normalised event fields are stored (no emails/phones/card data). Errors shown to clients are generic.
"""
import uuid
from collections.abc import Awaitable
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import transactional
from app.core.errors import AppError, ConflictError, NotFoundError, ProviderError, UnauthorizedError
from app.core.logging import get_logger
from app.integrations.payments.base import PaymentProvider, WebhookEvent
from app.integrations.payments.mock import MockPaymentProvider
from app.models.dispute import Dispute
from app.models.enums import DisputeStatus, NotificationType, OrderStatus, PaymentStatus, RefundStatus, UserRole
from app.models.payment import Payment
from app.models.payment_event import PaymentEvent
from app.models.refund import Refund
from app.models.user import User
from app.repositories.payment import PaymentRepository
from app.schemas.payment import CheckoutOut, PaymentOut, RefundOut
from app.services.audit import SYSTEM_ACTOR, Actor, AuditService, RequestContext
from app.services.notification import NotificationService
from app.services.order import IdempotencyConflict, OrderService
from app.services.transitions import DISPUTE_TRANSITIONS, PAYMENT_TRANSITIONS, assert_transition
from app.utils.hashing import sha256_hex
from app.utils.money import paise_to_rupees
from app.utils.time import utcnow

log = get_logger(__name__)
MAX_PAYMENTS_PER_ORDER = 5
OPEN_REFUND = [RefundStatus.REQUESTED, RefundStatus.PROCESSING]
COUNTED_REFUND = [RefundStatus.REQUESTED, RefundStatus.PROCESSING, RefundStatus.COMPLETED]
PAID_LIKE = {PaymentStatus.SUCCESS, PaymentStatus.REFUND_REQUESTED, PaymentStatus.REFUNDED}


class WebhookSignatureError(UnauthorizedError):
    code, message = "invalid_signature", "Invalid signature"


class WebhookMalformed(AppError):
    status_code, code, message = 400, "invalid_webhook", "Malformed webhook"


def to_out(p: Payment, refunds: list[Refund], provider: PaymentProvider, *, include_checkout: bool) -> PaymentOut:
    checkout = None
    if include_checkout and p.status in {PaymentStatus.PENDING, PaymentStatus.FAILED} and not p.provider_order_id.startswith("pending:"):
        checkout = CheckoutOut(provider=p.provider, key_id=provider.public_key_id, provider_order_id=p.provider_order_id,
                               amount=paise_to_rupees(p.amount_paise), amount_paise=p.amount_paise, currency=p.currency)
    return PaymentOut(id=p.id, order_id=p.order_id, status=p.status, amount=paise_to_rupees(p.amount_paise), currency=p.currency,
                      provider=p.provider, method=p.method, failure_reason=p.failure_reason, created_at=p.created_at, checkout=checkout,
                      refunds=[RefundOut(id=r.id, amount=paise_to_rupees(r.amount_paise), status=r.status, reason=r.reason,
                                         created_at=r.created_at) for r in refunds])


class PaymentService:
    def __init__(self, session: AsyncSession, settings: Settings, provider: PaymentProvider) -> None:
        self.session, self.settings, self.provider = session, settings, provider
        self.payments, self.orders = PaymentRepository(session), OrderService(session, settings)
        self.order_repo, self.audit, self.notify = self.orders.orders, AuditService(session), NotificationService(session)
        self.risk_queue: Any = None  # optional JobQueue: lets a failed payment trigger a (post-commit) risk assessment

    # ------------------------------------------------------------------ reads
    async def view(self, user: User, payment_id: uuid.UUID) -> PaymentOut:
        p = await self.payments.get(payment_id)
        o = await self.order_repo.get(p.order_id) if p else None
        if p is None or o is None or not (user.role == UserRole.ADMIN or user.id in (o.buyer_id, o.farmer_id)):
            raise NotFoundError("Payment not found")
        return to_out(p, await self.payments.refunds_for(p.id), self.provider, include_checkout=user.id == o.buyer_id)

    async def for_order(self, user: User, order_id: uuid.UUID) -> list[PaymentOut]:
        o = await self.orders.get(user, order_id)  # visibility rules reused (404 otherwise)
        return [to_out(p, await self.payments.refunds_for(p.id), self.provider, include_checkout=user.id == o.buyer_id)
                for p in await self.payments.for_order(order_id)]

    # ------------------------------------------------------------------ create
    async def create_payment(self, user: User, order_id: uuid.UUID, idem_key: str, ctx: RequestContext) -> tuple[PaymentOut, bool]:
        scoped = sha256_hex(f"{user.id}:{idem_key}")  # keys are per-user; stored hashed
        async with transactional(self.session):
            o = await self.order_repo.get_for_update(order_id)  # serialises concurrent attempts on the same order
            if o is None or o.buyer_id != user.id:
                raise NotFoundError("Order not found")
            existing = await self.payments.by_key(scoped)
            if existing is not None:
                if existing.order_id != o.id:
                    raise IdempotencyConflict()
                return to_out(existing, [], self.provider, include_checkout=True), False
            if o.status not in {OrderStatus.RESERVED, OrderStatus.PAYMENT_PENDING}:
                raise ConflictError(f"A {o.status.value} order cannot be paid")
            if o.reservation_expires_at and o.reservation_expires_at < utcnow():
                raise ConflictError("The reservation has expired; please place the order again")
            active = await self.payments.active_for_order(o.id)
            if active is not None:  # never run two open payments for one order
                return to_out(active, [], self.provider, include_checkout=True), False
            if await self.payments.count_for_order(o.id) >= MAX_PAYMENTS_PER_ORDER:
                raise ConflictError("Too many payment attempts for this order")
            p = Payment(order_id=o.id, payer_id=user.id, provider=self.provider.name, provider_order_id=f"pending:{uuid.uuid4()}",
                        amount_paise=o.total_amount_paise, currency=o.currency, status=PaymentStatus.CREATED, idempotency_key=scoped)
            self.session.add(p)
            await self.session.flush()
            self.audit.record(action="payment.created", entity_type="payment", entity_id=p.id, actor=Actor(user.id, user.role), ip=ctx.ip,
                              metadata={"order_id": str(o.id), "amount_paise": p.amount_paise, "provider": p.provider},
                              new_state={"status": "CREATED"})
            pid, amount, currency, oid = p.id, p.amount_paise, p.currency, o.id
        try:  # provider call happens OUTSIDE any DB transaction/lock
            po = await self.provider.create_order(amount_paise=amount, currency=currency, receipt=str(pid),
                                                  notes={"payment_id": str(pid), "order_id": str(oid)})
        except ProviderError:
            async with transactional(self.session):
                p = await self.payments.get_for_update(pid)
                p.status, p.failure_reason = PaymentStatus.FAILED, "provider_error"
                self.audit.record(action="payment.failed", entity_type="payment", entity_id=pid, actor=SYSTEM_ACTOR,
                                  metadata={"reason": "provider_error"}, previous_state={"status": "CREATED"}, new_state={"status": "FAILED"})
            raise
        async with transactional(self.session):
            p = await self.payments.get_for_update(pid)
            p.provider_order_id = po.provider_order_id
            assert_transition(PAYMENT_TRANSITIONS, p.status, PaymentStatus.PENDING)
            p.status = PaymentStatus.PENDING
            self.audit.record(action="payment.pending", entity_type="payment", entity_id=pid, actor=SYSTEM_ACTOR,
                              metadata={"provider_order_id": po.provider_order_id}, previous_state={"status": "CREATED"},
                              new_state={"status": "PENDING"})
        await self.orders.mark_payment_pending(oid)
        return to_out(await self.payments.get(pid), [], self.provider, include_checkout=True), True  # type: ignore[arg-type]

    # ------------------------------------------------------------------ webhook
    async def handle_webhook(self, raw: bytes, signature: str | None, header_event_id: str | None) -> str:
        if not self.provider.verify_webhook(raw, signature):  # BEFORE any DB access
            log.warning("webhook_bad_signature", provider=self.provider.name)
            raise WebhookSignatureError()
        try:
            ev = self.provider.parse_webhook(raw, header_event_id)
        except ValueError as exc:
            raise WebhookMalformed() from exc
        if ev is None:
            return "ignored"  # event types we do not act on
        async with transactional(self.session):  # 1) durable dedupe record (commits even if processing later fails)
            new_id = (await self.session.execute(pg_insert(PaymentEvent).values(
                id=uuid.uuid4(), provider=self.provider.name, provider_event_id=ev.event_id, event_type=ev.type,
                payload=ev.normalized()).on_conflict_do_nothing(constraint="uq_payment_events_provider_event")
                .returning(PaymentEvent.id))).scalar_one_or_none()
            if new_id is None:
                row = await self.session.scalar(select(PaymentEvent).where(
                    PaymentEvent.provider == self.provider.name, PaymentEvent.provider_event_id == ev.event_id)
                    .execution_options(populate_existing=True))
                if row.processed_at is not None:
                    return "duplicate"
                new_id = row.id  # seen but never finished (crash): re-apply (all steps are idempotent)
        return await self._process(new_id, ev)

    async def _process(self, event_row_id: uuid.UUID, ev: WebhookEvent) -> str:
        post: list[Awaitable[Any]] = []
        async with transactional(self.session):  # 2) apply atomically
            ev_row = await self.session.get(PaymentEvent, event_row_id, with_for_update=True, populate_existing=True)
            if ev_row.processed_at is not None:  # concurrent delivery of the same event finished first
                return "duplicate"
            outcome = await self._apply(ev, ev_row, post)
            ev_row.processed_at = utcnow()
            ev_row.payload = {**ev_row.payload, "outcome": outcome}
        for step in post:  # provider calls only after the commit
            try:
                await step
            except AppError as exc:
                log.error("post_commit_step_failed", error=exc.code)
        return outcome

    async def reprocess_event(self, event_row_id: uuid.UUID) -> str:
        """Recovery sweeper entry: re-applies a stored, never-finished event from its normalised payload (idempotent)."""
        row = await self.session.get(PaymentEvent, event_row_id, populate_existing=True)
        if row is None or row.processed_at is not None:
            return "skipped"
        fields = {k: v for k, v in row.payload.items() if k in WebhookEvent.__dataclass_fields__}
        return await self._process(event_row_id, WebhookEvent(**fields))

    async def _apply(self, ev: WebhookEvent, ev_row: PaymentEvent, post: list[Awaitable[Any]]) -> str:
        refund: Refund | None = None
        if ev.type.startswith("payment."):
            payment = await self.payments.by_provider_order(ev.provider_order_id or "")
        else:
            refund = await self.payments.refund_by_provider_id(ev.provider_refund_id or "")
            payment = (await self.payments.get(refund.payment_id)) if refund else (
                await self.payments.by_provider_payment(ev.provider_payment_id or ""))
        if payment is None:
            log.warning("webhook_unmatched", type=ev.type)
            return "unmatched"
        order = await self.order_repo.get_for_update(payment.order_id)  # lock order BEFORE payment
        payment = await self.payments.get_for_update(payment.id)
        # Assign the FK only AFTER both locks are held: the FK check takes a KEY SHARE lock on the payment row, which
        # would otherwise be acquired before the order lock and deadlock against another webhook (lock-order inversion).
        ev_row.payment_id = payment.id
        if ev.type == "payment.captured":
            return await self._captured(ev, payment, order, post)
        if ev.type == "payment.failed":
            return await self._failed(ev, payment, order, post)
        if refund is None:
            return "unmatched"
        refund = await self.payments.get_refund(refund.id)
        return await self._refund_event(ev, refund, payment, order)

    async def _captured(self, ev: WebhookEvent, p: Payment, order, post) -> str:  # noqa: ANN001
        if ev.amount_paise != p.amount_paise or (ev.currency or p.currency) != p.currency:
            self.audit.record(action="payment.amount_mismatch", entity_type="payment", entity_id=p.id, actor=SYSTEM_ACTOR,
                              metadata={"expected_paise": p.amount_paise, "received_paise": ev.amount_paise,
                                        "currency": ev.currency, "event_id": ev.event_id})
            await self.notify.notify_admins(NotificationType.SYSTEM, "Payment amount mismatch",
                                            f"Payment {str(p.id)[:8]} was rejected: amount did not match the order.", {"payment_id": str(p.id)})
            return "rejected_amount_mismatch"
        if p.status in PAID_LIKE:
            return "already_applied"
        assert_transition(PAYMENT_TRANSITIONS, p.status, PaymentStatus.SUCCESS)
        prev = p.status
        p.status, p.provider_payment_id, p.method, p.failure_reason = PaymentStatus.SUCCESS, ev.provider_payment_id, ev.method, None
        result = await self.orders.apply_paid_locked(order)
        duplicate = result == "already_paid" and await self.payments.other_success_for_order(order.id, p.id) is not None
        self.audit.record(action="payment.succeeded", entity_type="payment", entity_id=p.id, actor=SYSTEM_ACTOR,
                          metadata={"order_result": result, "provider_payment_id": ev.provider_payment_id, "event_id": ev.event_id},
                          previous_state={"status": prev.value}, new_state={"status": "SUCCESS"})
        if result == "late" or duplicate:  # money was taken but the order cannot use it -> refund it automatically
            reason = "duplicate_payment" if duplicate else "order_not_payable_at_capture"
            r = self._new_refund(p, p.amount_paise, reason, None)
            p.status = PaymentStatus.REFUND_REQUESTED
            await self.session.flush()
            self.audit.record(action="payment.auto_refund", entity_type="payment", entity_id=p.id, actor=SYSTEM_ACTOR,
                              metadata={"reason": reason, "refund_id": str(r.id)})
            await self.notify.notify_admins(NotificationType.SYSTEM, "Automatic refund initiated",
                                            f"Payment {str(p.id)[:8]} arrived for an unpayable order ({reason}).", {"payment_id": str(p.id)})
            post.append(self._dispatch_refund(r.id))
            return "applied_auto_refund"
        return "applied"

    async def _failed(self, ev: WebhookEvent, p: Payment, order, post: list[Awaitable[Any]]) -> str:  # noqa: ANN001
        if p.status in PAID_LIKE:
            return "ignored_stale"  # out-of-order: a later success already won
        if p.status == PaymentStatus.FAILED:
            return "already_applied"
        assert_transition(PAYMENT_TRANSITIONS, p.status, PaymentStatus.FAILED)
        prev = p.status
        p.status, p.failure_reason = PaymentStatus.FAILED, (ev.failure_reason or "payment_failed")[:300]
        self.audit.record(action="payment.failed", entity_type="payment", entity_id=p.id, actor=SYSTEM_ACTOR,
                          metadata={"reason": p.failure_reason, "code": ev.failure_code, "event_id": ev.event_id},
                          previous_state={"status": prev.value}, new_state={"status": "FAILED"})
        self.notify.add(p.payer_id, NotificationType.PAYMENT_FAILED, "Payment failed",
                        f"Your payment for order {str(order.id)[:8]} failed. You can try again before the reservation expires.",
                        {"order_id": str(order.id), "payment_id": str(p.id)})
        post.append(self._emit_risk(p.id))
        return "applied"

    async def _emit_risk(self, payment_id: uuid.UUID) -> None:
        from app.agents.fraud_risk.events import emit_risk_event
        await emit_risk_event(self.session, self.risk_queue, "payment.failed", payment_id, idempotency_key=f"risk:payment.failed:{payment_id}")

    # ------------------------------------------------------------------ refunds
    def _new_refund(self, p: Payment, amount: int, reason: str, requested_by: uuid.UUID | None, dispute_id: uuid.UUID | None = None) -> Refund:
        r = Refund(payment_id=p.id, amount_paise=amount, status=RefundStatus.REQUESTED, reason=reason, requested_by=requested_by,
                   dispute_id=dispute_id)
        self.session.add(r)
        return r

    async def _complete_refund(self, r: Refund, p: Payment, order) -> None:  # noqa: ANN001
        r.status = RefundStatus.COMPLETED
        await self.session.flush()
        done = await self.payments.refund_total(p.id, [RefundStatus.COMPLETED])
        if done >= p.amount_paise:
            assert_transition(PAYMENT_TRANSITIONS, p.status, PaymentStatus.REFUNDED)
            p.status = PaymentStatus.REFUNDED
            await self.orders.apply_refunded_locked(order)
            if r.dispute_id:
                await self._resolve_dispute_after_refund(r, order)
        elif not await self.payments.refund_total(p.id, OPEN_REFUND) and p.status == PaymentStatus.REFUND_REQUESTED:
            p.status = PaymentStatus.SUCCESS  # partial refund finished and nothing else is in flight
        self.audit.record(action="refund.completed", entity_type="refund", entity_id=r.id, actor=SYSTEM_ACTOR,
                          metadata={"payment_id": str(p.id), "amount_paise": r.amount_paise, "payment_status": p.status.value})
        self.notify.add(p.payer_id, NotificationType.SYSTEM, "Refund processed", f"Rs {paise_to_rupees(r.amount_paise)} has been refunded.",
                        {"payment_id": str(p.id), "refund_id": str(r.id), "kind": "refund"})

    async def _resolve_dispute_after_refund(self, r: Refund, order) -> None:  # noqa: ANN001
        """Lock order: order -> payment -> dispute (the same order DisputeService uses)."""
        d = await self.session.get(Dispute, r.dispute_id, with_for_update=True, populate_existing=True)
        if d is None or d.status != DisputeStatus.REFUND_REQUIRED:
            return
        assert_transition(DISPUTE_TRANSITIONS, d.status, DisputeStatus.RESOLVED)
        d.status, d.resolved_at = DisputeStatus.RESOLVED, utcnow()
        d.resolution = f"{d.resolution or ''} Refund completed.".strip()
        self.audit.record(action="dispute.resolved", entity_type="dispute", entity_id=d.id, actor=SYSTEM_ACTOR,
                          metadata={"via": "refund_completed", "refund_id": str(r.id)},
                          previous_state={"status": "REFUND_REQUIRED"}, new_state={"status": "RESOLVED"})
        for uid in (order.buyer_id, order.farmer_id):
            self.notify.add(uid, NotificationType.DISPUTE_UPDATED, "Dispute resolved", f"Dispute {str(d.id)[:8]} is resolved: the refund was completed.",
                            {"dispute_id": str(d.id)})

    async def _fail_refund(self, r: Refund, p: Payment, reason: str) -> None:
        r.status = RefundStatus.FAILED
        await self.session.flush()
        if p.status == PaymentStatus.REFUND_REQUESTED and not await self.payments.refund_total(p.id, OPEN_REFUND):
            p.status = PaymentStatus.SUCCESS
        self.audit.record(action="refund.failed", entity_type="refund", entity_id=r.id, actor=SYSTEM_ACTOR,
                          metadata={"payment_id": str(p.id), "reason": reason})
        await self.notify.notify_admins(NotificationType.SYSTEM, "Refund failed",
                                        f"Refund {str(r.id)[:8]} for payment {str(p.id)[:8]} failed ({reason}); manual follow-up needed.",
                                        {"refund_id": str(r.id)})

    async def _refund_event(self, ev: WebhookEvent, r: Refund, p: Payment, order) -> str:  # noqa: ANN001
        if r.status in {RefundStatus.COMPLETED, RefundStatus.FAILED}:
            return "already_applied"
        if ev.type == "refund.processed":
            await self._complete_refund(r, p, order)
        else:
            await self._fail_refund(r, p, "provider_reported_failure")
        return "applied"

    async def request_refund(self, admin: User, payment_id: uuid.UUID, amount_paise: int | None, reason: str,
                             ctx: RequestContext, dispute_id: uuid.UUID | None = None) -> Refund:
        """Admin-initiated (a sensitive, irreversible action: the route also blocks demo sessions)."""
        async with transactional(self.session):
            p0 = await self.payments.get(payment_id)
            if p0 is None:
                raise NotFoundError("Payment not found")
            order = await self.order_repo.get_for_update(p0.order_id)
            p = await self.payments.get_for_update(payment_id)
            if p.status not in {PaymentStatus.SUCCESS, PaymentStatus.REFUND_REQUESTED}:
                raise ConflictError(f"A {p.status.value} payment cannot be refunded")
            if order.status not in {OrderStatus.DISPUTED, OrderStatus.CANCELLED}:
                raise ConflictError("Open a dispute or cancel the order before refunding it")
            remaining = p.amount_paise - await self.payments.refund_total(p.id, COUNTED_REFUND)
            amount = amount_paise if amount_paise is not None else remaining
            if amount <= 0 or amount > remaining:
                raise ConflictError(f"Refund amount must be between 0.01 and {paise_to_rupees(remaining)}")
            r = self._new_refund(p, amount, reason, admin.id, dispute_id)
            if p.status == PaymentStatus.SUCCESS:
                p.status = PaymentStatus.REFUND_REQUESTED
            await self.session.flush()
            self.audit.record(action="refund.requested", entity_type="refund", entity_id=r.id, actor=Actor(admin.id, admin.role),
                              ip=ctx.ip, metadata={"payment_id": str(p.id), "amount_paise": amount, "reason": reason})
            rid = r.id
        await self._dispatch_refund(rid)
        return await self.payments.get_refund(rid)  # type: ignore[return-value]

    async def _dispatch_refund(self, refund_id: uuid.UUID) -> None:
        r = await self.payments.get_refund(refund_id)
        p = await self.payments.get(r.payment_id)  # type: ignore[union-attr]
        try:
            pr = await self.provider.create_refund(provider_payment_id=p.provider_payment_id or "", amount_paise=r.amount_paise,  # type: ignore[union-attr]
                                                   notes={"refund_id": str(refund_id)})
        except ProviderError:
            async with transactional(self.session):
                order = await self.order_repo.get_for_update(p.order_id)  # type: ignore[union-attr]
                p = await self.payments.get_for_update(p.id)  # type: ignore[union-attr]
                await self._fail_refund(await self.payments.get_refund(refund_id), p, "provider_error")  # type: ignore[arg-type]
            raise
        async with transactional(self.session):
            order = await self.order_repo.get_for_update(p.order_id)  # type: ignore[union-attr]
            p = await self.payments.get_for_update(p.id)  # type: ignore[union-attr]
            r = await self.payments.get_refund(refund_id)  # type: ignore[assignment]
            r.provider_refund_id, r.status = pr.provider_refund_id, RefundStatus.PROCESSING  # type: ignore[union-attr]
            if pr.status == "processed":
                await self._complete_refund(r, p, order)  # type: ignore[arg-type]

    # ------------------------------------------------------------------ demo (mock provider only)
    async def simulate(self, user: User, payment_id: uuid.UUID, outcome: str) -> str:
        """Demo/recruiter mode: push a correctly SIGNED webhook through the real pipeline. Mock provider + DEMO_MODE only."""
        if not (self.settings.DEMO_MODE and isinstance(self.provider, MockPaymentProvider)):
            raise NotFoundError()
        p = await self.payments.get(payment_id)
        if p is None or p.payer_id != user.id:
            raise NotFoundError("Payment not found")
        if p.status not in {PaymentStatus.PENDING, PaymentStatus.FAILED}:
            raise ConflictError(f"A {p.status.value} payment cannot be simulated")
        raw = MockPaymentProvider.payment_event("captured" if outcome == "success" else "failed", provider_order_id=p.provider_order_id,
                                                amount_paise=p.amount_paise, currency=p.currency,
                                                reason=None if outcome == "success" else "Simulated failure (demo)")
        return await self.handle_webhook(raw, self.provider.sign(raw), f"evt_sim_{uuid.uuid4().hex}")
