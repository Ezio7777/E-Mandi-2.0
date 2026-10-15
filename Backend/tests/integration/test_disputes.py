import asyncio
import uuid

from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.core.errors import ConflictError
from app.models.audit_log import AuditLog
from app.models.dispute import Dispute
from app.models.enums import NotificationType, OrderStatus, PaymentStatus
from app.models.notification import Notification
from app.models.refund import Refund
from app.models.user import User
from app.schemas.dispute import DisputeCreate
from app.services.audit import RequestContext
from app.services.dispute import DisputeService
from sqlalchemy import select, text

from tests.integration.conftest import bearer
from tests.integration.test_grading import make_admin
from tests.integration.test_matching_agent import buyer, farmer
from tests.integration.test_orders import order_row
from tests.integration.test_payments import MP, captured, deliver, pay_row, setup, start

D = "/api/v1/disputes"
O = "/api/v1/orders"
S = get_settings()
BODY = {"category": "QUALITY_ISSUE", "description": "Half of the tomatoes arrived rotten."}


async def paid(client, app_ctx, db, **kw):
    c = await start(client, db, **kw)
    assert (await deliver(client, app_ctx, captured(c))).json()["status"] == "applied"
    return c


async def dispute(client, c, who="bh", **over):
    return await client.post(D, json={"order_id": c["oid"], **BODY, **over}, headers=c[who])


async def drow(db, did):
    return await db.get(Dispute, uuid.UUID(did), populate_existing=True)


async def actions(db, entity):
    return [a.action for a in (await db.scalars(select(AuditLog).where(AuditLog.entity_type == entity).order_by(AuditLog.timestamp))).all()]


async def test_buyer_raises_dispute_order_locks_and_everyone_is_notified(app_ctx, client, db):
    admin = await make_admin(db, client)
    c = await paid(client, app_ctx, db)
    r = await dispute(client, c)
    d = r.json()["data"]
    assert r.status_code == 201 and d["status"] == "OPEN" and d["order_status"] == "DISPUTED" and d["refund_required"] is False
    assert d["raised_by"]["role"] == "BUYER" and [t["kind"] for t in d["timeline"]] == ["opened"]
    assert (await order_row(db, c["oid"])).status == OrderStatus.DISPUTED
    n = (await db.scalars(select(Notification).where(Notification.user_id == c["f1"], Notification.type == NotificationType.DISPUTE_UPDATED))).one()
    assert "quality issue" in n.body and n.data["dispute_id"] == d["id"]
    assert (await db.scalars(select(Notification).where(Notification.title == "New dispute to review"))).first()
    assert await actions(db, "dispute") == ["dispute.created"] and "order.disputed" in await actions(db, "order")
    assert (await client.get(f"{D}/{d['id']}", headers=admin)).status_code == 200


async def test_farmer_can_raise_dispute_on_confirmed_order(app_ctx, client, db):
    c = await paid(client, app_ctx, db)
    assert (await client.post(f"{O}/{c['oid']}/confirm", headers=c["fh"])).status_code == 200
    r = await dispute(client, c, "fh", category="PAYMENT_ISSUE", description="Buyer is refusing to accept delivery.")
    assert r.status_code == 201 and r.json()["data"]["raised_by"]["role"] == "FARMER"
    n = (await db.scalars(select(Notification).where(Notification.user_id == c["b1"], Notification.type == NotificationType.DISPUTE_UPDATED))).one()
    assert n


async def test_who_and_when_a_dispute_can_be_raised(app_ctx, client, db):
    admin = await make_admin(db, client)
    c = await setup(client, db)  # order is only RESERVED
    assert (await dispute(client, c)).status_code == 409
    await client.post("/api/v1/payments", json={"order_id": c["oid"]}, headers={**c["bh"], "Idempotency-Key": "pay-key-0001"})
    assert (await dispute(client, c)).status_code == 409  # PAYMENT_PENDING is not disputable either
    other_b, _ = await buyer(client, 2)
    other_f, _ = await farmer(client, 2)
    for who in (other_b, other_f):
        assert (await client.post(D, json={"order_id": c["oid"], **BODY}, headers=who)).status_code == 404
    assert (await client.post(D, json={"order_id": c["oid"], **BODY}, headers=admin)).status_code == 403
    assert (await client.post(D, json={"order_id": c["oid"], **BODY})).status_code == 401
    assert (await client.post(D, json={"order_id": str(uuid.uuid4()), **BODY}, headers=c["bh"])).status_code == 404
    assert (await order_row(db, c["oid"])).status != OrderStatus.DISPUTED


async def test_validation_and_single_dispute_per_order(app_ctx, client, db):
    c = await paid(client, app_ctx, db)
    for bad in ({"description": "too short"}, {"category": "BANANAS"}, {"status": "RESOLVED"}, {"raised_by": str(uuid.uuid4())}):
        assert (await dispute(client, c, **bad)).status_code == 422, bad
    assert (await dispute(client, c)).status_code == 201
    assert (await dispute(client, c, "fh")).status_code == 409  # the other party cannot open a second one


async def test_completed_orders_have_a_dispute_window(app_ctx, client, db):
    c = await paid(client, app_ctx, db)
    for step, who in (("confirm", "fh"), ("start-fulfillment", "fh"), ("complete", "bh")):
        assert (await client.post(f"{O}/{c['oid']}/{step}", headers=c[who])).status_code == 200
    await db.execute(text("UPDATE orders SET updated_at = now() - interval '8 days' WHERE id = :i"), {"i": c["oid"]})
    await db.commit()
    r = await dispute(client, c)
    assert r.status_code == 409 and "window" in r.json()["error"]["message"]
    await db.execute(text("UPDATE orders SET updated_at = now() - interval '2 days' WHERE id = :i"), {"i": c["oid"]})
    await db.commit()
    assert (await dispute(client, c)).status_code == 201


async def test_visibility_and_listing(app_ctx, client, db):
    admin = await make_admin(db, client)
    c1, c2 = await paid(client, app_ctx, db, n=1), await paid(client, app_ctx, db, n=2)
    d1 = (await dispute(client, c1)).json()["data"]
    d2 = (await dispute(client, c2)).json()["data"]
    assert (await client.get(f"{D}/{d1['id']}", headers=c2["bh"])).status_code == 404
    assert (await client.get(f"{D}/{d1['id']}", headers=c2["fh"])).status_code == 404
    for who in ("bh", "fh"):
        assert (await client.get(f"{D}/{d1['id']}", headers=c1[who])).status_code == 200
    mine = (await client.get(D, headers=c1["bh"])).json()["data"]["items"]
    assert [i["id"] for i in mine] == [d1["id"]] and (await client.get(D, headers=c1["fh"])).json()["data"]["items"][0]["id"] == d1["id"]
    allp = (await client.get(D, headers=admin)).json()["data"]
    assert {i["id"] for i in allp["items"]} == {d1["id"], d2["id"]}
    assert len((await client.get(f"{D}?limit=1", headers=admin)).json()["data"]["items"]) == 1
    cur = (await client.get(f"{D}?limit=1", headers=admin)).json()["data"]["next_cursor"]
    assert (await client.get(f"{D}?limit=1&cursor={cur}", headers=admin)).json()["data"]["items"][0]["id"] in {d1["id"], d2["id"]}
    assert (await client.get(f"{D}?status=CLOSED", headers=admin)).json()["data"]["items"] == []
    assert (await client.get(D)).status_code == 401


async def test_evidence_flow_and_admin_requests(app_ctx, client, db):
    admin = await make_admin(db, client)
    c = await paid(client, app_ctx, db)
    d = (await dispute(client, c)).json()["data"]
    u = f"{D}/{d['id']}"
    r = await client.post(f"{u}/request-evidence", json={"from_party": "farmer", "message": "Please share the packing photos."}, headers=admin)
    assert r.json()["data"]["status"] == "EVIDENCE_REQUESTED"
    assert (await db.scalars(select(Notification).where(Notification.user_id == c["f1"], Notification.title == "Evidence requested"))).one()
    assert (await db.scalars(select(Notification).where(Notification.user_id == c["b1"], Notification.title == "Evidence requested"))).first() is None
    e = await client.post(f"{u}/evidence", json={"note": "Packed at 6am, photos sent by WhatsApp."}, headers=c["fh"])
    assert e.status_code == 200 and e.json()["data"]["status"] == "UNDER_REVIEW"  # a reply moves it back to review
    await client.post(f"{u}/evidence", json={"note": "Photo shows rotten tomatoes in crate 3."}, headers=c["bh"])
    tl = (await client.get(u, headers=admin)).json()["data"]["timeline"]
    assert [(t["kind"], t["role"]) for t in tl] == [("opened", "BUYER"), ("admin_request", "ADMIN"), ("evidence", "FARMER"), ("evidence", "BUYER")]
    other, _ = await buyer(client, 2)
    assert (await client.post(f"{u}/evidence", json={"note": "I am not involved at all"}, headers=other)).status_code == 404
    assert (await client.post(f"{u}/evidence", json={"note": "admin posting as a party"}, headers=admin)).status_code == 403
    assert (await client.post(f"{u}/evidence", json={"note": "x"}, headers=c["bh"])).status_code == 422
    assert (await db.scalars(select(Notification).where(Notification.title == "New dispute evidence"))).first()
    assert "dispute.evidence_added" in await actions(db, "dispute") and "dispute.evidence_requested" in await actions(db, "dispute")


async def test_admin_only_actions_and_transition_rules(app_ctx, client, db):
    admin = await make_admin(db, client)
    c = await paid(client, app_ctx, db)
    d = (await dispute(client, c)).json()["data"]
    u = f"{D}/{d['id']}"
    for path, body in (("review", None), ("request-evidence", {"from_party": "both", "message": "send everything please"}),
                       ("resolve", {"outcome": "SELLER_FAVOURED", "resolution": "buyer claim unfounded here"}), ("close", None), ("refund", {})):
        for who in ("bh", "fh"):
            assert (await client.post(f"{u}/{path}", json=body, headers=c[who])).status_code == 403, (path, who)
    assert (await client.post(f"{u}/close", headers=admin)).status_code == 409  # cannot close an OPEN dispute
    assert (await client.post(f"{u}/refund", json={}, headers=admin)).status_code == 409  # no refund before a decision
    assert (await client.post(f"{u}/review", headers=admin)).json()["data"]["status"] == "UNDER_REVIEW"
    assert (await client.post(f"{u}/review", headers=admin)).status_code == 409  # already under review
    assert (await client.post(f"{u}/resolve", json={"outcome": "NOPE", "resolution": "invalid outcome here"}, headers=admin)).status_code == 422
    assert (await client.post(f"{u}/resolve", json={"outcome": "SELLER_FAVOURED", "resolution": "short"}, headers=admin)).status_code == 422


async def test_seller_favoured_resolution_completes_order_and_can_be_closed(app_ctx, client, db):
    admin = await make_admin(db, client)
    c = await paid(client, app_ctx, db)
    d = (await dispute(client, c)).json()["data"]
    u = f"{D}/{d['id']}"
    r = await client.post(f"{u}/resolve", json={"outcome": "SELLER_FAVOURED", "resolution": "Photos show goods in good condition."}, headers=admin)
    out = r.json()["data"]
    assert out["status"] == "RESOLVED" and out["order_status"] == "COMPLETED" and out["resolution"].startswith("Photos") and out["resolved_at"]
    assert (await order_row(db, c["oid"])).status == OrderStatus.COMPLETED
    assert (await pay_row(db, c["pid"])).status == PaymentStatus.SUCCESS  # no refund: money stays
    row = (await db.scalars(select(Dispute))).one()
    assert row.resolved_by is not None
    a = (await db.scalars(select(AuditLog).where(AuditLog.action == "dispute.resolved"))).one()
    assert a.actor_role == "ADMIN" and a.meta["outcome"] == "SELLER_FAVOURED" and a.new_state == {"status": "RESOLVED"}
    for uid in (c["b1"], c["f1"]):
        assert (await db.scalars(select(Notification).where(Notification.user_id == uid, Notification.title == "Dispute decision"))).one()
    assert (await client.post(f"{u}/resolve", json={"outcome": "SELLER_FAVOURED", "resolution": "deciding twice is wrong"}, headers=admin)).status_code == 409
    assert (await client.post(f"{u}/evidence", json={"note": "late evidence after decision"}, headers=c["bh"])).status_code == 409
    assert (await client.post(f"{u}/close", headers=admin)).json()["data"]["status"] == "CLOSED"
    assert (await client.post(f"{u}/close", headers=admin)).status_code == 409


async def test_buyer_refund_flow_auto_resolves_when_fully_refunded(app_ctx, client, db):
    admin = await make_admin(db, client)
    c = await paid(client, app_ctx, db)
    d = (await dispute(client, c)).json()["data"]
    u = f"{D}/{d['id']}"
    r = await client.post(f"{u}/resolve", json={"outcome": "BUYER_REFUND", "resolution": "Quality complaint upheld by evidence."}, headers=admin)
    assert r.json()["data"]["status"] == "REFUND_REQUIRED" and r.json()["data"]["refund_required"] is True
    assert (await order_row(db, c["oid"])).status == OrderStatus.DISPUTED  # order waits for the refund
    out = await client.post(f"{u}/refund", json={}, headers=admin)
    j = out.json()["data"]
    assert out.status_code == 201 and j["status"] == "RESOLVED" and j["order_status"] == "REFUNDED" and j["resolution"].endswith("Refund completed.")
    assert (await pay_row(db, c["pid"])).status == PaymentStatus.REFUNDED
    ref = (await db.scalars(select(Refund))).one()
    assert ref.dispute_id == uuid.UUID(d["id"]) and ref.requested_by is not None and "Quality" not in ref.reason and ref.amount_paise == 1425000
    assert "dispute.resolved" in await actions(db, "dispute") and await actions(db, "refund") == ["refund.requested", "refund.completed"]
    sysres = (await db.scalars(select(AuditLog).where(AuditLog.action == "dispute.resolved").order_by(AuditLog.timestamp.desc()))).first()
    assert sysres.actor_role == "SYSTEM" and sysres.meta["via"] == "refund_completed"
    assert (await client.post(f"{u}/refund", json={}, headers=admin)).status_code == 409  # nothing left to refund / not REFUND_REQUIRED


async def test_partial_dispute_refunds_keep_it_open_until_complete(app_ctx, client, db):
    admin = await make_admin(db, client)
    c = await paid(client, app_ctx, db)
    d = (await dispute(client, c)).json()["data"]
    u = f"{D}/{d['id']}"
    await client.post(f"{u}/resolve", json={"outcome": "BUYER_REFUND", "resolution": "Partial damage confirmed by photos."}, headers=admin)
    p1 = await client.post(f"{u}/refund", json={"amount": 5000.0, "reason": "partial damage compensation"}, headers=admin)
    assert p1.json()["data"]["status"] == "REFUND_REQUIRED" and p1.json()["data"]["order_status"] == "DISPUTED"
    p2 = await client.post(f"{u}/refund", json={}, headers=admin)  # remainder
    assert p2.json()["data"]["status"] == "RESOLVED" and p2.json()["data"]["order_status"] == "REFUNDED"
    assert sorted(r.amount_paise for r in (await db.scalars(select(Refund))).all()) == [500000, 925000]


async def test_async_provider_refund_resolves_dispute_on_webhook(app_ctx, client, db):
    admin = await make_admin(db, client)
    app_ctx.state.fake_provider.refund_status = "pending"
    c = await paid(client, app_ctx, db)
    d = (await dispute(client, c)).json()["data"]
    u = f"{D}/{d['id']}"
    await client.post(f"{u}/resolve", json={"outcome": "BUYER_REFUND", "resolution": "Buyer is owed a full refund."}, headers=admin)
    assert (await client.post(f"{u}/refund", json={}, headers=admin)).json()["data"]["status"] == "REFUND_REQUIRED"  # still waiting
    rf, pr = app_ctx.state.fake_provider.refunds[-1], await pay_row(db, c["pid"])
    ev = MP.refund_event("processed", refund_id=rf["id"], payment_id=pr.provider_payment_id, amount_paise=rf["amount"])
    assert (await deliver(client, app_ctx, ev)).json()["status"] == "applied"
    assert (await client.get(u, headers=admin)).json()["data"]["status"] == "RESOLVED"
    assert (await order_row(db, c["oid"])).status == OrderStatus.REFUNDED


async def test_cannot_favour_seller_while_a_refund_is_in_flight(app_ctx, client, db):
    admin = await make_admin(db, client)
    app_ctx.state.fake_provider.refund_status = "pending"
    c = await paid(client, app_ctx, db)
    d = (await dispute(client, c)).json()["data"]
    # an admin starts a refund straight through the payments API while the dispute is still open
    rr = await client.post(f"/api/v1/payments/{c['pid']}/refunds", json={"reason": "goodwill refund in progress"}, headers=admin)
    assert rr.status_code == 201
    res = await client.post(f"{D}/{d['id']}/resolve", json={"outcome": "SELLER_FAVOURED", "resolution": "conflicting decision attempt"}, headers=admin)
    assert res.status_code == 409 and "refund is in progress" in res.json()["error"]["message"]


async def test_demo_admin_can_review_but_never_decide_or_refund(app_ctx, client, db, demo_users):
    c = await paid(client, app_ctx, db)
    d = (await dispute(client, c)).json()["data"]
    demo_admin = bearer((await client.post("/api/v1/auth/demo", json={"kind": "admin"})).json()["data"])
    u = f"{D}/{d['id']}"
    assert (await client.post(f"{u}/review", headers=demo_admin)).status_code == 200
    assert (await client.post(f"{u}/request-evidence", json={"from_party": "both", "message": "Please add more detail."}, headers=demo_admin)).status_code == 200
    assert (await client.post(f"{u}/resolve", json={"outcome": "BUYER_REFUND", "resolution": "attempt by a demo session"}, headers=demo_admin)).status_code == 403
    assert (await client.post(f"{u}/refund", json={}, headers=demo_admin)).status_code == 403
    assert (await client.get(u, headers=demo_admin)).json()["data"]["status"] == "EVIDENCE_REQUESTED" and app_ctx.state.fake_provider.refunds == []


async def _admin_resolve(admin_id, did, outcome):
    async with get_sessionmaker()() as s:
        admin = await s.get(User, admin_id)
        try:
            await DisputeService(s, S).resolve(admin, did, outcome, "concurrent decision attempt", RequestContext())
            return "ok"
        except ConflictError:
            return "conflict"


async def test_concurrent_admin_decisions_apply_once(app_ctx, client, db):
    await make_admin(db, client)
    admin_id = (await db.scalars(select(User.id).where(User.email == "admin@example.com"))).one()
    c = await paid(client, app_ctx, db)
    d = (await dispute(client, c)).json()["data"]
    res = await asyncio.gather(*[_admin_resolve(admin_id, uuid.UUID(d["id"]), "SELLER_FAVOURED" if i % 2 else "BUYER_REFUND") for i in range(6)])
    assert res.count("ok") == 1 and res.count("conflict") == 5
    assert len([a for a in await actions(db, "dispute") if a in ("dispute.resolved", "dispute.refund_required")]) == 1


async def _raise(user_id, order_id):
    async with get_sessionmaker()() as s:
        user = await s.get(User, user_id)
        try:
            await DisputeService(s, S).create(user, DisputeCreate(order_id=order_id, category="OTHER", description="racing dispute creation"), RequestContext())
            return "ok"
        except ConflictError:
            return "conflict"


async def test_concurrent_dispute_creation_yields_exactly_one(app_ctx, client, db):
    c = await paid(client, app_ctx, db)
    res = await asyncio.gather(_raise(c["b1"], uuid.UUID(c["oid"])), _raise(c["f1"], uuid.UUID(c["oid"])),
                               _raise(c["b1"], uuid.UUID(c["oid"])), _raise(c["f1"], uuid.UUID(c["oid"])))
    assert sorted(res) == ["conflict", "conflict", "conflict", "ok"] and len((await db.scalars(select(Dispute))).all()) == 1


async def test_dispute_driven_full_refund_restocks_inventory(app_ctx, client, db):
    from tests.integration.test_payments import listing_row
    admin = await make_admin(db, client)
    c = await paid(client, app_ctx, db)
    assert (await listing_row(db, c["lid"])).quantity_kg == 300
    d = (await dispute(client, c)).json()["data"]
    u = f"{D}/{d['id']}"
    await client.post(f"{u}/resolve", json={"outcome": "BUYER_REFUND", "resolution": "Quality complaint upheld by evidence."}, headers=admin)
    assert (await client.post(f"{u}/refund", json={}, headers=admin)).status_code == 201
    await db.rollback()
    assert (await listing_row(db, c["lid"])).quantity_kg == 800
    assert (await order_row(db, c["oid"])).restocked_at is not None
