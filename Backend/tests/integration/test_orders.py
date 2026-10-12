import asyncio
import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.core.errors import InsufficientStockError
from app.models.audit_log import AuditLog
from app.models.buyer_requirement import BuyerRequirement
from app.models.enums import (
    AuthProvider, Grade, ListingStatus, MatchStatus, NotificationType, OrderStatus, RequirementStatus, UserRole,
)
from app.models.idempotency_key import IdempotencyKey
from app.models.listing import Listing
from app.models.match import Match
from app.models.notification import Notification
from app.models.order import Order
from app.models.user import User
from app.schemas.order import OrderCreate, OrderItemIn
from app.services.audit import RequestContext
from app.services.order import OrderService
from app.utils.time import utcnow
from app.workers.maintenance_jobs import expire_reservations_job
from tests.integration.conftest import bearer
from tests.integration.test_grading import make_admin
from tests.integration.test_matching_agent import buyer, db_farmer, farmer, mk

O = "/api/v1/orders"
KEY = {"Idempotency-Key": "order-key-0001"}
S = get_settings()


def body(lid, qty=500, **extra):
    return {"items": [{"listing_id": str(lid), "quantity_kg": qty}], **extra}


async def place(client, h, lid, qty=500, key="order-key-0001", **extra):
    r = await client.post(O, json=body(lid, qty, **extra), headers={**h, "Idempotency-Key": key} if key else h)
    return r


async def order_row(db, oid):
    return await db.get(Order, uuid.UUID(oid), populate_existing=True)


async def listing_row(db, lid):
    return await db.get(Listing, lid, populate_existing=True)


async def db_buyer(db, n):
    u = User(email=f"dbbuyer{n}-{uuid.uuid4().hex[:6]}@example.com", full_name=f"Buyer {n}", role=UserRole.BUYER,
             auth_provider=AuthProvider.LOCAL, email_verified=True)
    db.add(u)
    await db.commit()
    return u.id


async def test_create_order_amounts_reservation_audit_notification(app_ctx, client, db):
    fh, f1 = await farmer(client, 1)
    bh, b1 = await buyer(client)
    lid = await mk(db, f1, qty=800, price=2850)
    r = await place(client, bh, lid)
    d = r.json()["data"]
    assert r.status_code == 201 and d["status"] == "RESERVED" and d["currency"] == "INR"
    assert d["total_amount"] == 14250.0 and d["items"][0]["unit_price"] == 28.5 and d["items"][0]["line_total"] == 14250.0
    assert d["items"][0]["grade"] == "A" and d["items"][0]["crop_name"] == "Tomato" and d["items"][0]["quantity_kg"] == 500
    assert d["buyer"]["id"] == str(b1) and d["farmer"]["id"] == str(f1) and "email" not in str(d)
    l = await listing_row(db, lid)
    assert (l.reserved_kg, l.available_kg, l.status) == (500, 300, ListingStatus.ACTIVE)
    exp = (await order_row(db, d["id"])).reservation_expires_at
    assert timedelta(minutes=29) < exp - utcnow() < timedelta(minutes=31)
    a = (await db.scalars(select(AuditLog).where(AuditLog.action == "order.created"))).one()
    assert a.new_state == {"status": "RESERVED", "total_amount_paise": 1425000} and a.meta["items"][0]["unit_price_paise"] == 2850
    n = (await db.scalars(select(Notification).where(Notification.user_id == f1))).one()
    assert n.type == NotificationType.NEW_ORDER and "14250" in n.body and n.data["order_id"] == d["id"]
    for who in (fh, bh):
        assert (await client.get(f"{O}/{d['id']}", headers=who)).status_code == 200
    assert (await client.get(f"{O}/{d['id']}", headers=await make_admin(db, client))).status_code == 200


async def test_client_can_never_set_amounts_or_status(client, db):
    _, f1 = await farmer(client, 1)
    bh, _ = await buyer(client)
    lid = await mk(db, f1)
    for extra in ({"total_amount": 1}, {"status": "PAID"}, {"buyer_id": str(uuid.uuid4())}, {"currency": "USD"}):
        assert (await client.post(O, json={**body(lid), **extra}, headers=bh)).status_code == 422, extra
    bad_item = {"items": [{"listing_id": str(lid), "quantity_kg": 10, "unit_price": 1}]}
    assert (await client.post(O, json=bad_item, headers=bh)).status_code == 422
    assert (await listing_row(db, lid)).reserved_kg == 0


async def test_validation_and_visibility_rules(client, db):
    fh, f1 = await farmer(client, 1)
    bh, _ = await buyer(client)
    ok = await mk(db, f1, qty=100)
    draft = await mk(db, f1, status=ListingStatus.DRAFT)
    r = await place(client, bh, ok, qty=101)
    assert r.status_code == 409 and r.json()["error"]["code"] == "insufficient_stock"
    assert (await place(client, bh, draft)).status_code == 404  # drafts are invisible to buyers
    assert (await place(client, bh, uuid.uuid4())).status_code == 404
    assert (await client.post(O, json={"items": []}, headers=bh)).status_code == 422
    assert (await client.post(O, json={"items": [{"listing_id": str(ok), "quantity_kg": 1}] * 2}, headers=bh)).status_code == 422
    assert (await client.post(O, json={"items": [{"listing_id": str(ok), "quantity_kg": 1}] + [{"listing_id": str(uuid.uuid4()), "quantity_kg": 1}] * 10},
                              headers=bh)).status_code == 422
    for q in (0, -5, 1.2345):
        assert (await place(client, bh, ok, qty=q)).status_code == 422
    assert (await place(client, fh, ok, qty=10)).status_code == 403
    assert (await client.post(O, json=body(ok, 10))).status_code == 401
    assert (await place(client, bh, ok, qty=10, key="abc")).status_code == 422  # malformed Idempotency-Key
    assert (await listing_row(db, ok)).reserved_kg == 0  # nothing leaked from failed attempts


async def test_multi_item_order_is_atomic(client, db):
    _, f1 = await farmer(client, 1)
    bh, _ = await buyer(client)
    a, b = await mk(db, f1, qty=100, price=2000), await mk(db, f1, qty=50, price=3000, crop="Onion")
    bad = {"items": [{"listing_id": str(a), "quantity_kg": 60}, {"listing_id": str(b), "quantity_kg": 60}]}  # b is short
    assert (await client.post(O, json=bad, headers=bh)).status_code == 409
    assert (await listing_row(db, a)).reserved_kg == 0  # first item's reservation rolled back
    good = {"items": [{"listing_id": str(a), "quantity_kg": 60}, {"listing_id": str(b), "quantity_kg": 50}]}
    d = (await client.post(O, json=good, headers=bh)).json()["data"]
    assert d["total_amount"] == 60 * 20 + 50 * 30 and len(d["items"]) == 2
    assert (await listing_row(db, b)).status == ListingStatus.RESERVED  # fully reserved -> RESERVED


async def test_one_order_per_farmer(client, db):
    _, f1 = await farmer(client, 1)
    f2 = await db_farmer(db, 2)
    bh, _ = await buyer(client)
    a, b = await mk(db, f1), await mk(db, f2)
    r = await client.post(O, json={"items": [{"listing_id": str(a), "quantity_kg": 10}, {"listing_id": str(b), "quantity_kg": 10}]}, headers=bh)
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "items"
    assert (await listing_row(db, a)).reserved_kg == 0 and (await listing_row(db, b)).reserved_kg == 0


async def _create(buyer_id, listing_id, qty, key=None):
    async with get_sessionmaker()() as s:
        user = await s.get(User, buyer_id)
        try:
            o, created = await OrderService(s, S).create(
                user, OrderCreate(items=[OrderItemIn(listing_id=listing_id, quantity_kg=Decimal(qty))]), key, RequestContext())
            return "ok", created, o.id
        except InsufficientStockError:
            return "insufficient", False, None


async def test_no_overselling_with_concurrent_orders(client, db):
    f1 = await db_farmer(db, 1)
    lid = await mk(db, f1, qty=100)
    buyers = [await db_buyer(db, i) for i in range(30)]
    res = await asyncio.gather(*[_create(b, lid, 10) for b in buyers])
    assert [r[0] for r in res].count("ok") == 10 and [r[0] for r in res].count("insufficient") == 20
    l = await listing_row(db, lid)
    assert (l.reserved_kg, l.status) == (100, ListingStatus.RESERVED)
    assert len((await db.scalars(select(Order))).all()) == 10
    assert sum(o.total_amount_paise for o in (await db.scalars(select(Order))).all()) == 10 * 10 * 2850


async def test_idempotent_replay_and_conflicts(client, db):
    _, f1 = await farmer(client, 1)
    bh, _ = await buyer(client, 1)
    b2h, _ = await buyer(client, 2)
    lid = await mk(db, f1, qty=800)
    r1 = await place(client, bh, lid, 100)
    r2 = await place(client, bh, lid, 100)  # same key, same payload (double click / retry)
    assert (r1.status_code, r2.status_code) == (201, 200) and r2.headers["Idempotency-Replayed"] == "true"
    assert r1.json()["data"]["id"] == r2.json()["data"]["id"]
    assert len((await db.scalars(select(Order))).all()) == 1 and (await listing_row(db, lid)).reserved_kg == 100
    r3 = await place(client, bh, lid, 200)  # same key, DIFFERENT payload
    assert r3.status_code == 409 and r3.json()["error"]["code"] == "idempotency_key_reuse"
    assert (await listing_row(db, lid)).reserved_kg == 100
    r4 = await place(client, b2h, lid, 100)  # keys are scoped per user
    assert r4.status_code == 201 and r4.json()["data"]["id"] != r1.json()["data"]["id"]
    row = (await db.scalars(select(IdempotencyKey).where(IdempotencyKey.user_id == (await db.scalars(select(Order.buyer_id))).first()))).first()
    assert row.response_status == 201 and row.response_body["order_id"] == r1.json()["data"]["id"]
    assert await place(client, bh, lid, 100, key=None) is not None and (await listing_row(db, lid)).reserved_kg == 300  # no key: no dedupe


async def test_concurrent_requests_with_same_key_create_exactly_one_order(client, db):
    lid = await mk(db, await db_farmer(db, 1), qty=500)
    b = await db_buyer(db, 1)
    res = await asyncio.gather(*[_create(b, lid, 10, key="same-key-xyz-1") for _ in range(6)])
    assert [r[0] for r in res] == ["ok"] * 6 and [r[1] for r in res].count(True) == 1
    assert len({r[2] for r in res}) == 1
    assert (await listing_row(db, lid)).reserved_kg == 10 and len((await db.scalars(select(Order))).all()) == 1


async def test_cancel_releases_stock_and_enforces_who_can_cancel(client, db):
    fh, f1 = await farmer(client, 1)
    bh, b1 = await buyer(client, 1)
    b2h, _ = await buyer(client, 2)
    lid = await mk(db, f1, qty=500)
    oid = (await place(client, bh, lid, 500)).json()["data"]["id"]  # takes everything -> listing RESERVED
    assert (await listing_row(db, lid)).status == ListingStatus.RESERVED
    assert (await client.post(f"{O}/{oid}/cancel", headers=b2h)).status_code == 404
    c = await client.post(f"{O}/{oid}/cancel", json={"reason": "changed my mind"}, headers=bh)
    assert c.status_code == 200 and c.json()["data"]["status"] == "CANCELLED" and c.json()["data"]["cancel_reason"] == "changed my mind"
    l = await listing_row(db, lid)
    assert (l.reserved_kg, l.status) == (0, ListingStatus.ACTIVE)  # stock back, listing live again
    assert (await client.post(f"{O}/{oid}/cancel", headers=bh)).status_code == 409
    n = (await db.scalars(select(Notification).where(Notification.user_id == f1, Notification.title == "Order cancelled"))).one()
    assert "cancelled by the buyer" in n.body
    a = (await db.scalars(select(AuditLog).where(AuditLog.action == "order.cancelled"))).one()
    assert a.previous_state == {"status": "RESERVED"} and a.meta["reason"] == "changed my mind" and a.actor_role == "BUYER"
    # farmer may decline a RESERVED order (default reason) ...
    oid2 = (await place(client, bh, lid, 100, key="order-key-0002")).json()["data"]["id"]
    d = await client.post(f"{O}/{oid2}/cancel", headers=fh)
    assert d.json()["data"]["cancel_reason"] == "declined by farmer" and (await listing_row(db, lid)).reserved_kg == 0
    # ... but not once payment has started
    oid3 = (await place(client, bh, lid, 100, key="order-key-0003")).json()["data"]["id"]
    assert await OrderService(db, S).mark_payment_pending(uuid.UUID(oid3))
    assert (await client.post(f"{O}/{oid3}/cancel", headers=fh)).status_code == 409
    assert (await client.post(f"{O}/{oid3}/cancel", headers=bh)).status_code == 200  # buyer still can
    assert (await listing_row(db, lid)).reserved_kg == 0


async def test_payment_hooks_commit_inventory_and_handle_late_payment(client, db):
    fh, f1 = await farmer(client, 1)
    bh, b1 = await buyer(client)
    lid = await mk(db, f1, qty=800)
    svc = OrderService(db, S)
    oid = uuid.UUID((await place(client, bh, lid, 500)).json()["data"]["id"])
    before = (await order_row(db, str(oid))).reservation_expires_at
    assert await svc.mark_payment_pending(oid) and (await order_row(db, str(oid))).status == OrderStatus.PAYMENT_PENDING
    assert (await order_row(db, str(oid))).reservation_expires_at >= before  # extended so it can't expire mid-payment
    assert await svc.mark_paid(oid) == "paid"
    l = await listing_row(db, lid)
    assert (l.quantity_kg, l.reserved_kg, l.status) == (300, 0, ListingStatus.ACTIVE)  # 500 kg sold
    o = await order_row(db, str(oid))
    assert o.status == OrderStatus.PAID and o.reservation_expires_at is None
    assert await svc.mark_paid(oid) == "already_paid" and (await listing_row(db, lid)).quantity_kg == 300  # idempotent
    types = {n.type for n in (await db.scalars(select(Notification))).all()}
    assert NotificationType.PAYMENT_SUCCESSFUL in types
    assert (await client.post(f"{O}/{oid}/cancel", headers=bh)).status_code == 409  # paid orders go through refund/dispute
    # a late payment for an expired/cancelled order must NOT touch inventory (caller refunds)
    oid2 = uuid.UUID((await place(client, bh, lid, 100, key="order-key-0002")).json()["data"]["id"])
    await svc.mark_payment_pending(oid2)
    await client.post(f"{O}/{oid2}/cancel", headers=bh)
    assert await svc.mark_paid(oid2) == "late"
    assert (await listing_row(db, lid)).quantity_kg == 300
    # selling everything marks the listing SOLD
    oid3 = uuid.UUID((await place(client, bh, lid, 300, key="order-key-0003")).json()["data"]["id"])
    await svc.mark_payment_pending(oid3)
    assert await svc.mark_paid(oid3) == "paid" and (await listing_row(db, lid)).status == ListingStatus.SOLD


async def test_fulfillment_flow_roles_and_invalid_transitions(client, db):
    fh, f1 = await farmer(client, 1)
    bh, _ = await buyer(client)
    lid = await mk(db, f1, qty=500)
    oid = (await place(client, bh, lid, 100)).json()["data"]["id"]
    svc = OrderService(db, S)
    assert (await client.post(f"{O}/{oid}/confirm", headers=fh)).status_code == 409  # not paid yet
    assert (await client.post(f"{O}/{oid}/complete", headers=bh)).status_code == 409
    await svc.mark_payment_pending(uuid.UUID(oid))
    await svc.mark_paid(uuid.UUID(oid))
    assert (await client.post(f"{O}/{oid}/confirm", headers=bh)).status_code == 403  # buyers can't confirm
    assert (await client.post(f"{O}/{oid}/start-fulfillment", headers=fh)).status_code == 409  # must confirm first
    assert (await client.post(f"{O}/{oid}/confirm", headers=fh)).json()["data"]["status"] == "CONFIRMED"
    assert (await client.post(f"{O}/{oid}/start-fulfillment", headers=fh)).json()["data"]["status"] == "IN_FULFILLMENT"
    assert (await client.post(f"{O}/{oid}/complete", headers=fh)).status_code == 403  # farmers can't mark received
    assert (await client.post(f"{O}/{oid}/complete", headers=bh)).json()["data"]["status"] == "COMPLETED"
    assert (await client.post(f"{O}/{oid}/cancel", headers=bh)).status_code == 409
    acts = [a.action for a in (await db.scalars(select(AuditLog).where(AuditLog.entity_type == "order").order_by(AuditLog.timestamp))).all()]
    assert acts == ["order.created", "order.payment_pending", "order.paid", "order.confirmed", "order.in_fulfillment", "order.completed"]
    other_buyer, _ = await buyer(client, 2)
    assert (await client.post(f"{O}/{oid}/complete", headers=other_buyer)).status_code == 404


async def test_expired_reservations_are_released_by_the_sweeper(client, db):
    _, f1 = await farmer(client, 1)
    bh, b1 = await buyer(client)
    lid = await mk(db, f1, qty=300)
    stale = (await place(client, bh, lid, 100, key="order-key-0001")).json()["data"]["id"]
    fresh = (await place(client, bh, lid, 100, key="order-key-0002")).json()["data"]["id"]
    paid = (await place(client, bh, lid, 100, key="order-key-0003")).json()["data"]["id"]
    svc = OrderService(db, S)
    await svc.mark_payment_pending(uuid.UUID(paid))
    await svc.mark_paid(uuid.UUID(paid))
    for oid in (stale, paid):  # make `stale` (RESERVED) and `paid` look overdue
        (await order_row(db, oid)).reservation_expires_at = utcnow() - timedelta(minutes=1)
    await db.commit()
    assert await expire_reservations_job({}) == 1
    assert (await order_row(db, stale)).status == OrderStatus.CANCELLED and (await order_row(db, stale)).cancel_reason == "reservation_expired"
    assert (await order_row(db, fresh)).status == OrderStatus.RESERVED and (await order_row(db, paid)).status == OrderStatus.PAID
    l = await listing_row(db, lid)
    assert (l.reserved_kg, l.quantity_kg) == (100, 200)  # 100 sold, 100 still held by `fresh`, stale released
    a = (await db.scalars(select(AuditLog).where(AuditLog.action == "order.cancelled"))).one()
    assert a.actor_role == "SYSTEM" and a.meta["reason"] == "reservation_expired"
    assert (await db.scalars(select(Notification).where(Notification.user_id == b1, Notification.title == "Reservation expired"))).one()
    assert await expire_reservations_job({}) == 0  # idempotent


async def test_concurrent_sweepers_do_not_double_release(client, db):
    lid = await mk(db, await db_farmer(db, 1), qty=100)
    b = await db_buyer(db, 1)
    await _create(b, lid, 40)
    await _create(b, lid, 30)
    for o in (await db.scalars(select(Order))).all():
        o.reservation_expires_at = utcnow() - timedelta(minutes=5)
    await db.commit()
    res = await asyncio.gather(*[expire_reservations_job({}) for _ in range(4)])
    assert sum(res) == 2
    l = await listing_row(db, lid)
    assert (l.reserved_kg, l.quantity_kg) == (0, 100)


async def test_order_from_match_links_and_accepts_it(client, db):
    _, f1 = await farmer(client, 1)
    bh, b1 = await buyer(client, 1)
    b2h, _ = await buyer(client, 2)
    lid, other = await mk(db, f1), await mk(db, f1, crop="Onion")
    req = BuyerRequirement(buyer_id=b1, crop_name="Tomato", quantity_kg=Decimal(300), min_grade=Grade.A, location="Bengaluru",
                           max_price_paise=3500, status=RequirementStatus.MATCHED)
    db.add(req)
    await db.flush()
    m = Match(requirement_id=req.id, listing_id=lid, score=0.9, breakdown={}, status=MatchStatus.SUGGESTED)
    dism = Match(requirement_id=req.id, listing_id=other, score=0.5, breakdown={}, status=MatchStatus.DISMISSED)
    db.add_all([m, dism])
    await db.commit()
    assert (await client.post(O, json=body(lid, 100, match_id=str(m.id)), headers=b2h)).status_code == 404  # someone else's match
    assert (await client.post(O, json=body(other, 10, match_id=str(m.id)), headers=bh)).status_code == 422  # listing not in match
    assert (await client.post(O, json=body(other, 10, match_id=str(dism.id)), headers=bh)).status_code == 409  # dismissed
    r = await client.post(O, json=body(lid, 300, match_id=str(m.id)), headers=bh)
    assert r.status_code == 201 and r.json()["data"]["match_id"] == str(m.id) and r.json()["data"]["requirement_id"] == str(req.id)
    assert (await db.get(Match, m.id, populate_existing=True)).status == MatchStatus.ACCEPTED
    assert (await db.scalars(select(AuditLog).where(AuditLog.action == "match.accepted"))).one()
    again = await client.post(O, json=body(lid, 100, match_id=str(m.id)), headers={**bh, "Idempotency-Key": "other-key-12345"})
    assert again.status_code == 409  # a match can be accepted once
    assert (await listing_row(db, lid)).reserved_kg == 300  # the failed attempt reserved nothing


async def test_listing_orders_by_role_with_pagination_and_filter(client, db):
    fh, f1 = await farmer(client, 1)
    f2h, f2 = await farmer(client, 2)
    bh, _ = await buyer(client, 1)
    b2h, _ = await buyer(client, 2)
    l1, l2 = await mk(db, f1, qty=1000), await mk(db, f2, qty=1000)
    ids = [(await place(client, bh, l1, 10, key=f"order-key-000{i}")).json()["data"]["id"] for i in range(1, 4)]
    await place(client, bh, l2, 10, key="order-key-0009")
    await client.post(f"{O}/{ids[0]}/cancel", headers=bh)
    assert len((await client.get(O, headers=bh)).json()["data"]["items"]) == 4
    assert len((await client.get(O, headers=fh)).json()["data"]["items"]) == 3
    assert len((await client.get(O, headers=f2h)).json()["data"]["items"]) == 1
    assert (await client.get(O, headers=b2h)).json()["data"]["items"] == []
    assert len((await client.get(f"{O}?status=CANCELLED", headers=bh)).json()["data"]["items"]) == 1
    seen, cur = [], None
    for _ in range(4):
        p = (await client.get(f"{O}?limit=3" + (f"&cursor={cur}" if cur else ""), headers=bh)).json()["data"]
        seen += [i["id"] for i in p["items"]]
        cur = p["next_cursor"]
        if not cur:
            break
    assert len(seen) == 4 and len(set(seen)) == 4
    assert (await client.get(f"{O}?cursor=bad", headers=bh)).status_code == 422
    assert (await client.get(O)).status_code == 401
