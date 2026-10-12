"""Order lifecycle. Every amount is computed here from locked listing prices (never from the client).

Locking order is always: order row first, then listing rows (sorted by id inside InventoryService) - no deadlocks.
Inventory: RESERVED (reserve) -> PAID (commit sale) ; cancel/expiry release the reservation.
Payment hooks (mark_payment_pending / mark_paid) are called by the payment flow in Stage 13.
"""
import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import transactional
from app.core.errors import ConflictError, DomainValidationError, ForbiddenError, NotFoundError
from app.models.enums import MatchStatus, NotificationType, OrderStatus, UserRole
from app.models.idempotency_key import IdempotencyKey
from app.models.match import Match
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.user import User
from app.repositories.listing import ListingRepository
from app.repositories.order import OrderRepository
from app.repositories.requirement import RequirementRepository
from app.schemas.order import OrderCreate, OrderItemOut, OrderOut, OrderPage, PartyOut
from app.services.access import PUBLIC_LISTING_STATUSES
from app.services.audit import SYSTEM_ACTOR, Actor, AuditService, RequestContext
from app.services.inventory import InventoryService
from app.services.notification import NotificationService
from app.services.transitions import ORDER_TRANSITIONS, assert_transition
from app.utils.hashing import canonical_hash
from app.utils.money import fmt_kg, line_total_paise, paise_to_rupees
from app.utils.pagination import decode_cursor, encode_cursor
from app.utils.time import utcnow

IDEM_SCOPE, IDEM_TTL = "order.create", timedelta(hours=24)
UNPAID_RESERVED = {OrderStatus.RESERVED, OrderStatus.PAYMENT_PENDING}
BUYER_CANCELLABLE = {OrderStatus.PENDING, OrderStatus.RESERVED, OrderStatus.PAYMENT_PENDING}


class IdempotencyConflict(ConflictError):
    code, message = "idempotency_key_reuse", "This Idempotency-Key was already used with a different request"


def to_out(o: Order) -> OrderOut:
    return OrderOut(
        id=o.id, status=o.status, buyer=PartyOut(id=o.buyer_id, name=o.buyer.full_name),
        farmer=PartyOut(id=o.farmer_id, name=o.farmer.full_name),
        items=[OrderItemOut(listing_id=i.listing_id, crop_name=i.listing.crop_name, quantity_kg=i.quantity_kg,
                            unit_price=paise_to_rupees(i.unit_price_paise), line_total=paise_to_rupees(i.line_total_paise),
                            grade=i.grade_at_purchase) for i in o.items],
        total_amount=paise_to_rupees(o.total_amount_paise), currency=o.currency,
        reservation_expires_at=o.reservation_expires_at, delivery_address=o.delivery_address, notes=o.notes,
        cancel_reason=o.cancel_reason, match_id=o.match_id, requirement_id=o.requirement_id,
        created_at=o.created_at, updated_at=o.updated_at)


class OrderService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session, self.settings = session, settings
        self.orders, self.listings = OrderRepository(session), ListingRepository(session)
        self.inventory, self.audit, self.notify = InventoryService(session), AuditService(session), NotificationService(session)

    # ------------------------------------------------------------------ helpers
    def _visible(self, user: User, o: Order | None) -> Order:
        if o is None or not (user.role == UserRole.ADMIN or user.id in (o.buyer_id, o.farmer_id)):
            raise NotFoundError("Order not found")  # no existence leak
        return o

    def _transition(self, o: Order, target: OrderStatus, actor: Actor, ip: str | None = None, **meta) -> None:
        prev = o.status
        assert_transition(ORDER_TRANSITIONS, prev, target)
        o.status = target
        self.audit.record(action=f"order.{target.value.lower()}", entity_type="order", entity_id=o.id, actor=actor, ip=ip,
                          metadata=meta, previous_state={"status": prev.value}, new_state={"status": target.value})

    def _release_payload(self, o: Order) -> list[tuple[uuid.UUID, Decimal]]:
        return [(i.listing_id, i.quantity_kg) for i in o.items]

    async def _cancel_locked(self, o: Order, actor: Actor, reason: str, ip: str | None = None) -> None:
        was_reserved = o.status in UNPAID_RESERVED
        self._transition(o, OrderStatus.CANCELLED, actor, ip, reason=reason)
        o.cancel_reason = reason
        if was_reserved:
            await self.inventory.release_many(self._release_payload(o))

    # ------------------------------------------------------------------ queries
    async def get(self, user: User, order_id: uuid.UUID) -> Order:
        return self._visible(user, await self.orders.get(order_id))

    async def list(self, user: User, status: OrderStatus | None, cursor: str | None, limit: int) -> OrderPage:
        rows = await self.orders.list_for(user.id, user.role, status, decode_cursor(cursor) if cursor else None, limit)
        more, rows = len(rows) > limit, rows[:limit]
        return OrderPage(items=[to_out(r) for r in rows],
                         next_cursor=encode_cursor(rows[-1].created_at, rows[-1].id) if more else None)

    # ------------------------------------------------------------------ create
    async def create(self, user: User, data: OrderCreate, idem_key: str | None, ctx: RequestContext) -> tuple[Order, bool]:
        """Returns (order, created). created=False means an idempotent replay of an earlier identical request."""
        if user.role != UserRole.BUYER:
            raise ForbiddenError("Only buyers can place orders")
        req_hash = canonical_hash({"items": sorted((str(i.listing_id), str(i.quantity_kg)) for i in data.items),
                                   "address": data.delivery_address, "notes": data.notes,
                                   "match": str(data.match_id) if data.match_id else None})
        async with transactional(self.session):
            idem_id = None
            if idem_key:
                idem_id = (await self.session.execute(pg_insert(IdempotencyKey).values(
                    id=uuid.uuid4(), user_id=user.id, scope=IDEM_SCOPE, key=idem_key, request_hash=req_hash,
                    expires_at=utcnow() + IDEM_TTL).on_conflict_do_nothing(constraint="uq_idempotency_user_scope_key")
                    .returning(IdempotencyKey.id))).scalar_one_or_none()
                if idem_id is None:  # key seen before (a concurrent first request has already committed)
                    row = await self.session.scalar(select(IdempotencyKey).where(
                        IdempotencyKey.user_id == user.id, IdempotencyKey.scope == IDEM_SCOPE, IdempotencyKey.key == idem_key)
                        .execution_options(populate_existing=True))
                    if row.request_hash != req_hash:
                        raise IdempotencyConflict()
                    oid = (row.response_body or {}).get("order_id")
                    if not oid:
                        raise ConflictError("A request with this Idempotency-Key is still being processed")
                    return await self.orders.get(uuid.UUID(oid)), False  # type: ignore[return-value]

            # ---- pre-checks on unlocked rows (cheap; authoritative re-check happens under lock in reserve_many)
            listings = {}
            for it in data.items:
                l = await self.listings.get(it.listing_id)
                if l is None or l.status not in PUBLIC_LISTING_STATUSES:
                    raise NotFoundError("Listing not found")  # drafts/archived listings are invisible to buyers
                listings[it.listing_id] = l
            farmer_ids = {l.farmer_id for l in listings.values()}
            if len(farmer_ids) != 1:
                raise DomainValidationError("An order can only contain listings from one farmer; place one order per farmer",
                                            details=[{"field": "items", "message": "multiple farmers"}])
            match = await self._resolve_match(user, data)

            # ---- atomic reservation (row locks, sorted) -> prices come from the LOCKED rows
            locked = await self.inventory.reserve_many([(i.listing_id, i.quantity_kg) for i in data.items])
            o = Order(buyer_id=user.id, farmer_id=next(iter(farmer_ids)), status=OrderStatus.PENDING, total_amount_paise=0,
                      currency="INR", delivery_address=data.delivery_address, notes=data.notes, idempotency_key=idem_key,
                      requirement_id=match.requirement_id if match else None, match_id=match.id if match else None)
            total = 0
            for it in data.items:
                l = locked[it.listing_id]
                line = line_total_paise(it.quantity_kg, l.base_price_paise)
                total += line
                o.items.append(OrderItem(listing_id=l.id, quantity_kg=it.quantity_kg, unit_price_paise=l.base_price_paise,
                                         line_total_paise=line, grade_at_purchase=l.ai_grade))
            o.total_amount_paise = total
            self.session.add(o)
            await self.session.flush()
            assert_transition(ORDER_TRANSITIONS, o.status, OrderStatus.RESERVED)
            o.status = OrderStatus.RESERVED
            o.reservation_expires_at = utcnow() + timedelta(minutes=self.settings.RESERVATION_TTL_MINUTES)
            self.audit.record(
                action="order.created", entity_type="order", entity_id=o.id, actor=Actor(user.id, user.role), ip=ctx.ip,
                metadata={"farmer_id": str(o.farmer_id), "match_id": str(match.id) if match else None,
                          "items": [{"listing_id": str(i.listing_id), "kg": str(i.quantity_kg), "unit_price_paise": i.unit_price_paise}
                                    for i in o.items]},
                new_state={"status": "RESERVED", "total_amount_paise": total})
            if match:
                match.status = MatchStatus.ACCEPTED
                self.audit.record(action="match.accepted", entity_type="match", entity_id=match.id, actor=Actor(user.id, user.role),
                                  ip=ctx.ip, metadata={"order_id": str(o.id)})
            self.notify.add(o.farmer_id, NotificationType.NEW_ORDER, "New order received",
                            f"{user.full_name} ordered {', '.join(f'{fmt_kg(i.quantity_kg)} kg {listings[i.listing_id].crop_name}' for i in o.items)} "
                            f"(Rs {paise_to_rupees(total)}).", {"order_id": str(o.id)})
            if idem_id:
                row = await self.session.get(IdempotencyKey, idem_id)
                row.response_status, row.response_body = 201, {"order_id": str(o.id)}
            oid = o.id
        return await self.orders.get(oid), True  # type: ignore[return-value]

    async def _resolve_match(self, user: User, data: OrderCreate) -> Match | None:
        if data.match_id is None:
            return None
        m = await self.session.scalar(select(Match).where(Match.id == data.match_id).with_for_update())
        req = await RequirementRepository(self.session).get(m.requirement_id) if m else None
        if m is None or req is None or req.buyer_id != user.id:
            raise NotFoundError("Match not found")
        if m.listing_id not in {i.listing_id for i in data.items}:
            raise DomainValidationError("The order must include the matched listing",
                                        details=[{"field": "match_id", "message": "listing not in order"}])
        if m.status != MatchStatus.SUGGESTED:
            raise ConflictError(f"This match is already {m.status.value.lower()}")
        return m

    # ------------------------------------------------------------------ buyer / farmer actions
    async def cancel(self, user: User, order_id: uuid.UUID, reason: str | None, ctx: RequestContext) -> Order:
        async with transactional(self.session):
            o = self._visible(user, await self.orders.get_for_update(order_id))
            is_buyer, is_farmer = user.id == o.buyer_id, user.id == o.farmer_id
            if not (is_buyer or is_farmer):
                raise ForbiddenError()
            allowed = BUYER_CANCELLABLE if is_buyer else {OrderStatus.RESERVED}  # farmers may only decline before payment starts
            if o.status not in allowed:
                hint = " Paid orders are handled through refunds/disputes." if o.status == OrderStatus.PAID else ""
                raise ConflictError(f"A {o.status.value} order cannot be cancelled by the {'buyer' if is_buyer else 'farmer'}.{hint}")
            await self._cancel_locked(o, Actor(user.id, user.role), reason or ("cancelled by buyer" if is_buyer else "declined by farmer"), ctx.ip)
            other = o.farmer_id if is_buyer else o.buyer_id
            self.notify.add(other, NotificationType.SYSTEM, "Order cancelled",
                            f"Order {str(o.id)[:8]} was {'cancelled by the buyer' if is_buyer else 'declined by the farmer'}.",
                            {"order_id": str(o.id), "kind": "order"})
        return await self.orders.get(order_id)  # type: ignore[return-value]

    async def _step(self, user: User, order_id: uuid.UUID, *, role: UserRole, target: OrderStatus, ctx: RequestContext) -> Order:
        async with transactional(self.session):
            o = self._visible(user, await self.orders.get_for_update(order_id))
            owner = o.farmer_id if role == UserRole.FARMER else o.buyer_id
            if user.id != owner:
                raise ForbiddenError(f"Only the order's {role.value.lower()} can do this")
            self._transition(o, target, Actor(user.id, user.role), ctx.ip)
            other = o.buyer_id if role == UserRole.FARMER else o.farmer_id
            self.notify.add(other, NotificationType.SYSTEM, f"Order {target.value.lower().replace('_', ' ')}",
                            f"Order {str(o.id)[:8]} is now {target.value.replace('_', ' ')}.", {"order_id": str(o.id), "kind": "order"})
        return await self.orders.get(order_id)  # type: ignore[return-value]

    async def confirm(self, user: User, order_id: uuid.UUID, ctx: RequestContext) -> Order:
        return await self._step(user, order_id, role=UserRole.FARMER, target=OrderStatus.CONFIRMED, ctx=ctx)

    async def start_fulfillment(self, user: User, order_id: uuid.UUID, ctx: RequestContext) -> Order:
        return await self._step(user, order_id, role=UserRole.FARMER, target=OrderStatus.IN_FULFILLMENT, ctx=ctx)

    async def complete(self, user: User, order_id: uuid.UUID, ctx: RequestContext) -> Order:
        return await self._step(user, order_id, role=UserRole.BUYER, target=OrderStatus.COMPLETED, ctx=ctx)

    # ------------------------------------------------------------------ payment hooks (Stage 13 callers)
    async def mark_payment_pending(self, order_id: uuid.UUID) -> bool:
        """RESERVED -> PAYMENT_PENDING and extend the reservation so an in-flight payment is not expired under it."""
        async with transactional(self.session):
            o = await self.orders.get_for_update(order_id)
            if o is None or o.status not in {OrderStatus.RESERVED, OrderStatus.PAYMENT_PENDING}:
                return False
            if o.status == OrderStatus.RESERVED:
                self._transition(o, OrderStatus.PAYMENT_PENDING, SYSTEM_ACTOR)
            o.reservation_expires_at = utcnow() + timedelta(minutes=self.settings.RESERVATION_TTL_MINUTES)
        return True

    async def mark_paid(self, order_id: uuid.UUID) -> str:
        """Standalone wrapper: locks the order and applies payment in its own transaction."""
        async with transactional(self.session):
            o = await self.orders.get_for_update(order_id)
            if o is None:
                raise NotFoundError("Order not found")
            return await self.apply_paid_locked(o)

    async def apply_refunded_locked(self, o: Order) -> bool:
        """DISPUTED/CANCELLED -> REFUNDED. Caller holds the order lock and the surrounding transaction."""
        if o.status not in {OrderStatus.DISPUTED, OrderStatus.CANCELLED}:
            return False
        self._transition(o, OrderStatus.REFUNDED, SYSTEM_ACTOR)
        return True

    async def apply_paid_locked(self, o: Order) -> str:
        """PAYMENT_PENDING (or RESERVED, if the provider confirmed before we marked it pending) -> PAID and COMMIT the sale.
        Caller holds the order lock + transaction, so payment, order and inventory change atomically.
        Returns 'paid' | 'already_paid' | 'late' (order cancelled/expired: caller must refund)."""
        if o.status == OrderStatus.PAID:
            return "already_paid"
        if o.status == OrderStatus.RESERVED:  # webhook raced ahead of mark_payment_pending
            self._transition(o, OrderStatus.PAYMENT_PENDING, SYSTEM_ACTOR)
        if o.status != OrderStatus.PAYMENT_PENDING:
            return "late"
        await self.inventory.commit_sale_many(self._release_payload(o))
        self._transition(o, OrderStatus.PAID, SYSTEM_ACTOR, total_amount_paise=o.total_amount_paise)
        o.reservation_expires_at = None
        self.notify.add(o.farmer_id, NotificationType.PAYMENT_SUCCESSFUL, "Payment received",
                        f"Order {str(o.id)[:8]} has been paid (Rs {paise_to_rupees(o.total_amount_paise)}).", {"order_id": str(o.id)})
        self.notify.add(o.buyer_id, NotificationType.PAYMENT_SUCCESSFUL, "Payment successful",
                        f"Your payment of Rs {paise_to_rupees(o.total_amount_paise)} was received.", {"order_id": str(o.id)})
        return "paid"

    # ------------------------------------------------------------------ recovery sweeper
    async def expire_reservations(self, limit: int = 100) -> int:
        """Cancels unpaid orders whose reservation window passed and releases their stock. Idempotent; safe to run concurrently."""
        async with transactional(self.session):
            expired = await self.orders.lock_expired(utcnow(), limit)
            for o in expired:
                await self._cancel_locked(o, SYSTEM_ACTOR, "reservation_expired")
                self.notify.add(o.buyer_id, NotificationType.SYSTEM, "Reservation expired",
                                f"Order {str(o.id)[:8]} was cancelled because payment was not completed in time.",
                                {"order_id": str(o.id), "kind": "order"})
        return len(expired)
