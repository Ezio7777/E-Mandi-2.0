import asyncio
import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.database import get_sessionmaker
from app.core.errors import ProviderError
from app.integrations.payments.mock import MockPaymentProvider
from app.models.audit_log import AuditLog
from app.models.enums import (
    ListingStatus, NotificationType, OrderStatus, PaymentStatus, RefundStatus,
)
from app.models.listing import Listing
from app.models.notification import Notification
from app.models.order import Order
from app.models.payment import Payment
from app.models.payment_event import PaymentEvent
from app.models.refund import Refund
from app.services.payment import PaymentService
from app.utils.time import utcnow
from tests.integration.conftest import bearer
from tests.integration.test_grading import make_admin
from tests.integration.test_matching_agent import buyer, db_farmer, farmer, mk
from tests.integration.test_orders import listing_row, order_row, place

P = "/api/v1/payments"
O = "/api/v1/orders"
S = get_settings()
MP = MockPaymentProvider


async def setup(client, db, qty=800, order_kg=500, n=1):
    fh, f1 = await farmer(client, n)
    bh, b1 = await buyer(client, n)
    lid = await mk(db, f1, qty=qty)
    oid = (await place(client, bh, lid, order_kg)).json()["data"]["id"]
    return dict(fh=fh, f1=f1, bh=bh, b1=b1, lid=lid, oid=oid)


async def pay(client, h, oid, key="pay-key-0001", **extra):
    return await client.post(P, json={"order_id": oid, **extra}, headers={**h, "Idempotency-Key": key})


async def start(client, db, **kw):
    c = await setup(client, db, **kw)
    r = await pay(client, c["bh"], c["oid"])
    c.update(pid=r.json()["data"]["id"], po=r.json()["data"]["checkout"]["provider_order_id"], pay=r.json()["data"])
    return c


async def deliver(client, app_ctx, raw, *, sig=None, event_id=None):
    prov = app_ctx.state.fake_provider
    return await client.post(f"{P}/webhook", content=raw, headers={
        "X-Mock-Signature": sig if sig is not None else prov.sign(raw), "X-Mock-Event-Id": event_id or f"evt_{uuid.uuid4().hex}",
        "Content-Type": "application/json"})


def captured(c, amount=1425000, **kw):
    return MP.payment_event("captured", provider_order_id=c["po"], amount_paise=amount, **kw)


async def pay_row(db, pid):
    return await db.get(Payment, uuid.UUID(pid), populate_existing=True)


async def events(db):
    return (await db.scalars(select(PaymentEvent))).all()


async def actions(db, entity=None):
    q = select(AuditLog).order_by(AuditLog.timestamp)
    if entity:
        q = q.where(AuditLog.entity_type == entity)
    return [a.action for a in (await db.scalars(q)).all()]


# ------------------------------------------------------------------ create
async def test_create_payment_charges_server_computed_total(app_ctx, client, db):
    c = await setup(client, db)
    r = await pay(client, c["bh"], c["oid"])
    d = r.json()["data"]
    assert r.status_code == 201 and d["status"] == "PENDING" and d["amount"] == 14250.0 and d["provider"] == "mock"
    assert d["checkout"]["key_id"] == "rzp_test_mockkey" and d["checkout"]["amount_paise"] == 1425000
    assert d["checkout"]["provider_order_id"].startswith("order_mock_") and "secret" not in json.dumps(d).lower()
    assert app_ctx.state.fake_provider.orders[0]["amount"] == 1425000  # what the provider was asked to charge
    assert (await order_row(db, c["oid"])).status == OrderStatus.PAYMENT_PENDING
    assert await actions(db, "payment") == ["payment.created", "payment.pending"]
    for bad in ({"amount": 1}, {"amount_paise": 1}, {"status": "SUCCESS"}):
        assert (await pay(client, c["bh"], c["oid"], key=f"k-{uuid.uuid4().hex}", **bad)).status_code == 422  # clients cannot send amounts


async def test_create_payment_authz_and_header_rules(client, db):
    c = await setup(client, db)
    b2, _ = await buyer(client, 2)
    assert (await client.post(P, json={"order_id": c["oid"]}, headers=c["bh"])).status_code == 422  # Idempotency-Key required
    assert (await pay(client, c["bh"], c["oid"], key="short")).status_code == 422
    assert (await pay(client, c["fh"], c["oid"])).status_code == 403
    assert (await pay(client, b2, c["oid"])).status_code == 404  # not your order
    assert (await client.post(P, json={"order_id": c["oid"]}, headers={"Idempotency-Key": "pay-key-0001"})).status_code == 401
    assert (await pay(client, c["bh"], str(uuid.uuid4()))).status_code == 404


async def test_create_payment_idempotency_and_single_open_payment(app_ctx, client, db):
    c = await setup(client, db, qty=2000)
    r1, r2 = await pay(client, c["bh"], c["oid"]), await pay(client, c["bh"], c["oid"])
    assert (r1.status_code, r2.status_code) == (201, 200) and r2.headers["Idempotency-Replayed"] == "true"
    assert r1.json()["data"]["id"] == r2.json()["data"]["id"] and len(app_ctx.state.fake_provider.orders) == 1
    r3 = await pay(client, c["bh"], c["oid"], key="pay-key-OTHER-1")  # new key, same order: reuse the open payment
    assert r3.status_code == 200 and r3.json()["data"]["id"] == r1.json()["data"]["id"]
    oid2 = (await place(client, c["bh"], c["lid"], 100, key="order-key-0002")).json()["data"]["id"]
    r4 = await pay(client, c["bh"], oid2)  # same key, different order
    assert r4.status_code == 409 and r4.json()["error"]["code"] == "idempotency_key_reuse"
    assert len((await db.scalars(select(Payment))).all()) == 1


async def test_cannot_pay_unpayable_orders(client, db):
    c = await setup(client, db, qty=2000)
    (await order_row(db, c["oid"])).reservation_expires_at = utcnow() - timedelta(minutes=1)
    await db.commit()
    assert (await pay(client, c["bh"], c["oid"])).status_code == 409  # reservation expired
    oid2 = (await place(client, c["bh"], c["lid"], 50, key="order-key-0002")).json()["data"]["id"]
    await client.post(f"{O}/{oid2}/cancel", headers=c["bh"])
    assert (await pay(client, c["bh"], oid2, key="pay-key-0002")).status_code == 409  # cancelled
    assert (await db.scalars(select(Payment))).all() == []


async def test_provider_outage_marks_payment_failed_and_allows_retry(app_ctx, client, db):
    c = await setup(client, db)
    app_ctx.state.fake_provider.fail_create = True
    r = await pay(client, c["bh"], c["oid"])
    assert r.status_code == 502 and r.json()["error"]["code"] == "provider_error"
    p = (await db.scalars(select(Payment))).one()
    assert (p.status, p.failure_reason) == (PaymentStatus.FAILED, "provider_error")
    assert (await order_row(db, c["oid"])).status == OrderStatus.RESERVED  # order untouched, stock still held
    app_ctx.state.fake_provider.fail_create = False
    assert (await pay(client, c["bh"], c["oid"], key="pay-key-retry-1")).status_code == 201


async def test_attempt_cap_per_order(app_ctx, client, db):
    c = await setup(client, db)
    app_ctx.state.fake_provider.fail_create = True
    codes = [(await pay(client, c["bh"], c["oid"], key=f"pay-key-{i:04d}")).status_code for i in range(6)]
    assert codes == [502] * 5 + [409]


# ------------------------------------------------------------------ webhook: success path
async def test_captured_webhook_pays_order_and_commits_inventory_atomically(app_ctx, client, db):
    c = await start(client, db)
    r = await deliver(client, app_ctx, captured(c, payment_id="pay_abc"))
    assert r.status_code == 200 and r.json() == {"status": "applied"}
    p = await pay_row(db, c["pid"])
    assert (p.status, p.provider_payment_id, p.method) == (PaymentStatus.SUCCESS, "pay_abc", "upi")
    o = await order_row(db, c["oid"])
    assert o.status == OrderStatus.PAID and o.reservation_expires_at is None
    l = await listing_row(db, c["lid"])
    assert (l.quantity_kg, l.reserved_kg) == (300, 0)  # 500 kg sold, atomically with the payment
    (ev,) = await events(db)
    assert ev.processed_at and ev.payment_id == p.id and ev.payload["outcome"] == "applied"
    assert set(ev.payload) <= {"event_id", "type", "provider_order_id", "provider_payment_id", "amount_paise", "currency", "method", "outcome"}
    assert await actions(db, "payment") == ["payment.created", "payment.pending", "payment.succeeded"]
    types = [n.type for n in (await db.scalars(select(Notification).where(Notification.type == NotificationType.PAYMENT_SUCCESSFUL))).all()]
    assert len(types) == 2  # buyer + farmer
    pv = (await client.get(f"{P}/{c['pid']}", headers=c["bh"])).json()["data"]
    assert pv["status"] == "SUCCESS" and pv["checkout"] is None  # no checkout once paid


async def test_duplicate_events_are_acknowledged_without_effect(app_ctx, client, db):
    c = await start(client, db)
    raw = captured(c)
    assert (await deliver(client, app_ctx, raw, event_id="evt_dup_1")).json()["status"] == "applied"
    assert (await deliver(client, app_ctx, raw, event_id="evt_dup_1")).json()["status"] == "duplicate"
    assert len(await events(db)) == 1 and (await listing_row(db, c["lid"])).quantity_kg == 300  # not committed twice
    # same payment, NEW event id (provider re-sent under another id): idempotent at the payment level
    assert (await deliver(client, app_ctx, raw, event_id="evt_dup_2")).json()["status"] == "already_applied"
    assert (await listing_row(db, c["lid"])).quantity_kg == 300


async def test_event_recorded_but_never_processed_is_reapplied(app_ctx, client, db):
    c = await start(client, db)
    db.add(PaymentEvent(provider="mock", provider_event_id="evt_crash_1", event_type="payment.captured", payload={}))  # crashed mid-way
    await db.commit()
    r = await deliver(client, app_ctx, captured(c), event_id="evt_crash_1")
    assert r.json()["status"] == "applied" and (await order_row(db, c["oid"])).status == OrderStatus.PAID
    assert len(await events(db)) == 1


# ------------------------------------------------------------------ webhook: security
async def test_invalid_signatures_are_rejected_before_any_db_write(app_ctx, client, db):
    c = await start(client, db)
    raw = captured(c)
    good = app_ctx.state.fake_provider.sign(raw)
    cases = {"wrong": "0" * 64, "empty": "", "other-body": app_ctx.state.fake_provider.sign(raw + b" "), "truncated": good[:-2]}
    for name, sig in cases.items():
        r = await client.post(f"{P}/webhook", content=raw, headers={"X-Mock-Signature": sig, "X-Mock-Event-Id": "evt_x"})
        assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_signature" and r.json()["error"]["message"] == "Invalid signature", name
    assert (await client.post(f"{P}/webhook", content=raw)).status_code == 401  # header missing entirely
    assert await events(db) == [] and (await order_row(db, c["oid"])).status == OrderStatus.PAYMENT_PENDING


async def test_unconfigured_webhook_secret_rejects_everything(app_ctx, client, db):
    c = await start(client, db)
    raw = captured(c)
    NOSECRET = Settings(ENVIRONMENT="test", JWT_SECRET="x" * 40, PAYMENT_WEBHOOK_SECRET="")  # env secret explicitly cleared
    app_ctx.state.fake_provider = MP(NOSECRET)
    from app.core.dependencies import get_payment_provider
    app_ctx.dependency_overrides[get_payment_provider] = lambda: app_ctx.state.fake_provider
    forged = MP(NOSECRET).sign(raw)  # HMAC computed with the empty key
    r = await client.post(f"{P}/webhook", content=raw, headers={"X-Mock-Signature": forged})
    assert r.status_code == 401 and await events(db) == []


async def test_malformed_unknown_and_oversized_webhooks(app_ctx, client, db):
    c = await start(client, db)
    bad = b'{"event": "payment.captured"'
    assert (await deliver(client, app_ctx, bad)).status_code == 400
    unknown = json.dumps({"event": "order.paid", "payload": {}}).encode()
    assert (await deliver(client, app_ctx, unknown)).json()["status"] == "ignored" and await events(db) == []
    ghost = MP.payment_event("captured", provider_order_id="order_does_not_exist", amount_paise=100)
    assert (await deliver(client, app_ctx, ghost)).json()["status"] == "unmatched"
    (ev,) = await events(db)
    assert ev.payment_id is None and ev.processed_at  # kept for audit; no state changed
    big = b"{" + b" " * (300 * 1024) + b"}"
    assert (await deliver(client, app_ctx, big)).status_code == 400
    assert (await order_row(db, c["oid"])).status == OrderStatus.PAYMENT_PENDING


async def test_amount_or_currency_mismatch_is_rejected_and_flagged(app_ctx, client, db):
    admin = await make_admin(db, client)
    c = await start(client, db)
    for raw in (captured(c, amount=100), captured(c, amount=1425001), MP.payment_event(
            "captured", provider_order_id=c["po"], amount_paise=1425000, currency="USD")):
        assert (await deliver(client, app_ctx, raw)).json()["status"] == "rejected_amount_mismatch"
    assert (await pay_row(db, c["pid"])).status == PaymentStatus.PENDING
    assert (await order_row(db, c["oid"])).status == OrderStatus.PAYMENT_PENDING and (await listing_row(db, c["lid"])).quantity_kg == 800
    assert (await actions(db)).count("payment.amount_mismatch") == 3
    assert (await db.scalars(select(Notification).where(Notification.title == "Payment amount mismatch"))).first()
    _ = admin
    assert (await deliver(client, app_ctx, captured(c))).json()["status"] == "applied"  # the correct amount still works


# ------------------------------------------------------------------ webhook: failures & ordering
async def test_failed_payment_then_retry_success(app_ctx, client, db):
    c = await start(client, db)
    f = MP.payment_event("failed", provider_order_id=c["po"], amount_paise=1425000, reason="Insufficient funds")
    assert (await deliver(client, app_ctx, f)).json()["status"] == "applied"
    p = await pay_row(db, c["pid"])
    assert (p.status, p.failure_reason) == (PaymentStatus.FAILED, "Insufficient funds")
    assert (await order_row(db, c["oid"])).status == OrderStatus.PAYMENT_PENDING  # stock still held for a retry
    n = (await db.scalars(select(Notification).where(Notification.type == NotificationType.PAYMENT_FAILED))).one()
    assert n.user_id == c["b1"] and "try again" in n.body
    pv = (await client.get(f"{P}/{c['pid']}", headers=c["bh"])).json()["data"]
    assert pv["status"] == "FAILED" and pv["failure_reason"] == "Insufficient funds"
    assert (await deliver(client, app_ctx, captured(c))).json()["status"] == "applied"  # buyer retried on the same provider order
    assert (await pay_row(db, c["pid"])).status == PaymentStatus.SUCCESS and (await order_row(db, c["oid"])).status == OrderStatus.PAID
    assert (await deliver(client, app_ctx, f)).json()["status"] == "ignored_stale"  # late failure event cannot undo success
    assert (await pay_row(db, c["pid"])).status == PaymentStatus.SUCCESS


async def test_second_attempt_after_failure_and_duplicate_charge_is_auto_refunded(app_ctx, client, db):
    c = await start(client, db, qty=800)
    f = MP.payment_event("failed", provider_order_id=c["po"], amount_paise=1425000)
    await deliver(client, app_ctx, f)
    r2 = await pay(client, c["bh"], c["oid"], key="pay-key-0002")  # first is FAILED, so a new payment is allowed
    assert r2.status_code == 201 and r2.json()["data"]["id"] != c["pid"]
    c2 = {**c, "po": r2.json()["data"]["checkout"]["provider_order_id"]}
    assert (await deliver(client, app_ctx, captured(c2))).json()["status"] == "applied"
    assert (await order_row(db, c["oid"])).status == OrderStatus.PAID
    out = (await deliver(client, app_ctx, captured(c))).json()["status"]  # the FIRST payment succeeds late => double charge
    assert out == "applied_auto_refund"
    p1 = await pay_row(db, c["pid"])
    assert p1.status == PaymentStatus.REFUNDED
    r = (await db.scalars(select(Refund))).one()
    assert (r.reason, r.requested_by, r.status, r.amount_paise) == ("duplicate_payment", None, RefundStatus.COMPLETED, 1425000)
    assert (await order_row(db, c["oid"])).status == OrderStatus.PAID  # the order itself is untouched
    assert (await listing_row(db, c["lid"])).quantity_kg == 300  # sold exactly once
    assert "payment.auto_refund" in await actions(db)


async def test_late_payment_for_cancelled_order_is_refunded_without_touching_stock(app_ctx, client, db):
    c = await start(client, db)
    assert (await client.post(f"{O}/{c['oid']}/cancel", headers=c["bh"])).status_code == 200  # buyer abandons mid-payment
    assert (await listing_row(db, c["lid"])).reserved_kg == 0
    assert (await deliver(client, app_ctx, captured(c))).json()["status"] == "applied_auto_refund"
    p = await pay_row(db, c["pid"])
    assert p.status == PaymentStatus.REFUNDED
    assert (await order_row(db, c["oid"])).status == OrderStatus.REFUNDED  # CANCELLED -> REFUNDED
    l = await listing_row(db, c["lid"])
    assert (l.quantity_kg, l.reserved_kg, l.status) == (800, 0, ListingStatus.ACTIVE)
    r = (await db.scalars(select(Refund))).one()
    assert r.reason == "order_not_payable_at_capture" and r.status == RefundStatus.COMPLETED
    assert (await db.scalars(select(Notification).where(Notification.title == "Refund processed", Notification.user_id == c["b1"]))).one()


# ------------------------------------------------------------------ refunds (admin, sensitive)
async def paid_disputed(client, app_ctx, db, **kw):
    c = await start(client, db, **kw)
    await deliver(client, app_ctx, captured(c))
    (await order_row(db, c["oid"])).status = OrderStatus.DISPUTED
    await db.commit()
    return c


async def test_admin_full_refund_completes_payment_and_order(app_ctx, client, db):
    admin = await make_admin(db, client)
    c = await paid_disputed(client, app_ctx, db)
    r = await client.post(f"{P}/{c['pid']}/refunds", json={"reason": "goods spoiled on delivery"}, headers=admin)
    d = r.json()["data"]
    assert r.status_code == 201 and d["status"] == "REFUNDED" and d["refunds"][0]["status"] == "COMPLETED" and d["refunds"][0]["amount"] == 14250.0
    assert (await order_row(db, c["oid"])).status == OrderStatus.REFUNDED
    assert app_ctx.state.fake_provider.refunds[0]["amount"] == 1425000 and app_ctx.state.fake_provider.refunds[0]["payment_id"]
    assert [a for a in await actions(db, "refund")] == ["refund.requested", "refund.completed"]
    ra = (await db.scalars(select(AuditLog).where(AuditLog.action == "refund.requested"))).one()
    assert ra.actor_role == "ADMIN" and ra.meta["reason"] == "goods spoiled on delivery"
    assert (await client.post(f"{P}/{c['pid']}/refunds", json={"reason": "again please"}, headers=admin)).status_code == 409


async def test_partial_refunds_and_limits(app_ctx, client, db):
    admin = await make_admin(db, client)
    c = await paid_disputed(client, app_ctx, db)
    url = f"{P}/{c['pid']}/refunds"
    r1 = await client.post(url, json={"amount": 5000.00, "reason": "partial damage claim"}, headers=admin)
    assert r1.status_code == 201 and r1.json()["data"]["status"] == "SUCCESS"  # partial done, nothing in flight
    assert (await order_row(db, c["oid"])).status == OrderStatus.DISPUTED
    assert (await client.post(url, json={"amount": 9250.01, "reason": "too much refund"}, headers=admin)).status_code == 409  # > remaining
    for bad in ({"amount": 0, "reason": "zero refund"}, {"amount": -5, "reason": "negative"}, {"amount": 1.234, "reason": "fractions"}, {"reason": "x"}):
        assert (await client.post(url, json=bad, headers=admin)).status_code == 422
    r2 = await client.post(url, json={"reason": "refund the remainder"}, headers=admin)  # default = remaining
    assert r2.json()["data"]["status"] == "REFUNDED" and [x["amount"] for x in r2.json()["data"]["refunds"]] == [5000.0, 9250.0]
    assert (await order_row(db, c["oid"])).status == OrderStatus.REFUNDED


async def test_refund_authorization_and_preconditions(app_ctx, client, db, demo_users):
    admin = await make_admin(db, client)
    demo_admin = bearer((await client.post("/api/v1/auth/demo", json={"kind": "admin"})).json()["data"])
    c = await start(client, db)
    url, body = f"{P}/{c['pid']}/refunds", {"reason": "needs a refund now"}
    assert (await client.post(url, json=body, headers=admin)).status_code == 409  # payment not paid yet
    await deliver(client, app_ctx, captured(c))
    assert (await client.post(url, json=body, headers=admin)).status_code == 409  # order PAID, not disputed/cancelled
    for who in (c["bh"], c["fh"]):
        assert (await client.post(url, json=body, headers=who)).status_code == 403
    assert (await client.post(url, json=body)).status_code == 401
    (await order_row(db, c["oid"])).status = OrderStatus.DISPUTED
    await db.commit()
    assert (await client.post(url, json=body, headers=demo_admin)).status_code == 403  # demo admins can never move money
    assert app_ctx.state.fake_provider.refunds == []
    assert (await client.post(f"{P}/{uuid.uuid4()}/refunds", json=body, headers=admin)).status_code == 404


async def test_refund_completed_by_webhook_when_provider_is_asynchronous(app_ctx, client, db):
    admin = await make_admin(db, client)
    app_ctx.state.fake_provider.refund_status = "pending"
    c = await paid_disputed(client, app_ctx, db)
    r = await client.post(f"{P}/{c['pid']}/refunds", json={"reason": "async provider refund"}, headers=admin)
    assert r.json()["data"]["status"] == "REFUND_REQUESTED" and r.json()["data"]["refunds"][0]["status"] == "PROCESSING"
    rf = app_ctx.state.fake_provider.refunds[-1]
    pr = await pay_row(db, c["pid"])
    ok = MP.refund_event("processed", refund_id=rf["id"], payment_id=pr.provider_payment_id, amount_paise=rf["amount"])
    assert (await deliver(client, app_ctx, ok, event_id="evt_rf_1")).json()["status"] == "applied"
    assert (await pay_row(db, c["pid"])).status == PaymentStatus.REFUNDED and (await order_row(db, c["oid"])).status == OrderStatus.REFUNDED
    assert (await deliver(client, app_ctx, ok, event_id="evt_rf_1")).json()["status"] == "duplicate"


async def test_failed_refunds_roll_back_to_paid_and_alert_admins(app_ctx, client, db, monkeypatch):
    admin = await make_admin(db, client)
    app_ctx.state.fake_provider.refund_status = "pending"
    c = await paid_disputed(client, app_ctx, db)
    await client.post(f"{P}/{c['pid']}/refunds", json={"reason": "will fail at provider"}, headers=admin)
    rf, pr = app_ctx.state.fake_provider.refunds[-1], await pay_row(db, c["pid"])
    bad = MP.refund_event("failed", refund_id=rf["id"], payment_id=pr.provider_payment_id, amount_paise=rf["amount"])
    assert (await deliver(client, app_ctx, bad)).json()["status"] == "applied"
    assert (await pay_row(db, c["pid"])).status == PaymentStatus.SUCCESS
    assert (await db.scalars(select(Refund))).one().status == RefundStatus.FAILED
    assert (await db.scalars(select(Notification).where(Notification.title == "Refund failed"))).first()
    # provider error at request time -> 502, refund FAILED, payment back to SUCCESS, admin can retry
    async def boom(**kw):
        raise ProviderError("down")
    monkeypatch.setattr(app_ctx.state.fake_provider, "create_refund", boom)
    r = await client.post(f"{P}/{c['pid']}/refunds", json={"reason": "second try fails too"}, headers=admin)
    assert r.status_code == 502 and (await pay_row(db, c["pid"])).status == PaymentStatus.SUCCESS
    assert [x.status for x in (await db.scalars(select(Refund).order_by(Refund.created_at))).all()] == [RefundStatus.FAILED] * 2


# ------------------------------------------------------------------ demo simulator
async def test_demo_simulator_runs_the_real_pipeline(app_ctx, client, db):
    c = await start(client, db)
    other, _ = await buyer(client, 2)
    assert (await client.post(f"{P}/{c['pid']}/simulate", json={"outcome": "success"}, headers=other)).status_code == 404
    assert (await client.post(f"{P}/{c['pid']}/simulate", json={"outcome": "success"}, headers=c["fh"])).status_code == 403
    f = await client.post(f"{P}/{c['pid']}/simulate", json={"outcome": "failure"}, headers=c["bh"])
    assert f.json()["data"]["status"] == "FAILED" and "Simulated" in f.json()["data"]["failure_reason"]
    s = await client.post(f"{P}/{c['pid']}/simulate", json={"outcome": "success"}, headers=c["bh"])
    assert s.json()["data"]["status"] == "SUCCESS" and (await order_row(db, c["oid"])).status == OrderStatus.PAID
    assert len(await events(db)) == 2 and all(e.processed_at for e in await events(db))  # went through verification + dedupe
    assert (await client.post(f"{P}/{c['pid']}/simulate", json={"outcome": "success"}, headers=c["bh"])).status_code == 409


async def test_simulator_is_unavailable_outside_demo_mock_mode(app_ctx, client, db):
    c = await start(client, db)
    from app.core.config import get_settings as gs
    app_ctx.dependency_overrides[gs] = lambda: Settings(DEMO_MODE=False, ENVIRONMENT="test")
    assert (await client.post(f"{P}/{c['pid']}/simulate", json={"outcome": "success"}, headers=c["bh"])).status_code == 404
    app_ctx.dependency_overrides.pop(gs)
    assert (await pay_row(db, c["pid"])).status == PaymentStatus.PENDING


# ------------------------------------------------------------------ concurrency
async def _webhook(provider, raw, event_id):
    async with get_sessionmaker()() as s:
        return await PaymentService(s, S, provider).handle_webhook(raw, provider.sign(raw), event_id)


async def test_concurrent_deliveries_apply_exactly_once(app_ctx, client, db):
    c = await start(client, db)
    prov, raw = app_ctx.state.fake_provider, captured(c)
    same = await asyncio.gather(*[_webhook(prov, raw, "evt_same") for _ in range(6)])
    assert sorted(same).count("applied") == 1 and all(r in ("applied", "duplicate") for r in same)
    assert (await listing_row(db, c["lid"])).quantity_kg == 300 and len(await events(db)) == 1

    c2 = await start(client, db, n=2)
    raw2 = captured(c2)
    diff = await asyncio.gather(*[_webhook(prov, raw2, f"evt_diff_{i}") for i in range(6)])  # same payment, different event ids
    assert sorted(diff).count("applied") == 1 and set(diff) <= {"applied", "already_applied"}
    assert (await listing_row(db, c2["lid"])).quantity_kg == 300
    assert (await order_row(db, c2["oid"])).status == OrderStatus.PAID


async def test_payment_and_cancellation_race_never_loses_or_double_books_stock(app_ctx, client, db):
    c = await start(client, db)
    prov = app_ctx.state.fake_provider

    async def cancel():
        return (await client.post(f"{O}/{c['oid']}/cancel", headers=c["bh"])).status_code

    res = await asyncio.gather(_webhook(prov, captured(c), "evt_race"), cancel())
    o = await order_row(db, c["oid"])
    l = await listing_row(db, c["lid"])
    p = await pay_row(db, c["pid"])
    if o.status == OrderStatus.PAID:      # payment won: cancel must have been refused
        assert res[1] == 409 and (l.quantity_kg, l.reserved_kg) == (300, 0) and p.status == PaymentStatus.SUCCESS
    else:                                  # cancel won: payment auto-refunded, stock fully restored
        assert res[0] == "applied_auto_refund" and o.status == OrderStatus.REFUNDED
        assert (l.quantity_kg, l.reserved_kg) == (800, 0) and p.status == PaymentStatus.REFUNDED


# ------------------------------------------------------------------ visibility
async def test_payment_visibility_rules(app_ctx, client, db):
    c = await start(client, db)
    b2, _ = await buyer(client, 2)
    f2, _ = await farmer(client, 2)
    admin = await make_admin(db, client)
    seller = (await client.get(f"{P}/{c['pid']}", headers=c["fh"])).json()["data"]
    assert seller["checkout"] is None and seller["amount"] == 14250.0  # farmer sees status, never checkout data
    assert (await client.get(f"{P}/{c['pid']}", headers=c["bh"])).json()["data"]["checkout"]["key_id"] == "rzp_test_mockkey"
    assert (await client.get(f"{P}/{c['pid']}", headers=admin)).status_code == 200
    for who in (b2, f2):
        assert (await client.get(f"{P}/{c['pid']}", headers=who)).status_code == 404
        assert (await client.get(f"{P}/order/{c['oid']}", headers=who)).status_code == 404
    lst = (await client.get(f"{P}/order/{c['oid']}", headers=c["bh"])).json()["data"]
    assert len(lst) == 1 and lst[0]["id"] == c["pid"]
    assert (await client.get(f"{P}/{c['pid']}")).status_code == 401
