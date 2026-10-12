import json
import uuid

from sqlalchemy import select

from app.agents.fraud_risk.agent import FraudRiskAgent
from app.core.config import get_settings
from app.integrations.llm_common import LLMProviderError
from app.models.agent_execution import AgentExecution
from app.models.anomaly_event import AnomalyEvent
from app.models.audit_log import AuditLog
from app.models.crop_grading_result import CropGradingResult
from app.models.enums import (
    AgentName, AgentStatus, AnomalySeverity, AnomalyStatus, GradingProvider, Grade, ListingStatus, NotificationType, PendingActionStatus,
    PendingActionType, DisputeStatus, OrderStatus,
)
from app.models.listing import Listing
from app.models.listing_image import ListingImage
from app.models.notification import Notification
from app.models.pending_action import PendingAction
from app.models.user import User
from app.workers.queue import RecordingJobQueue
from app.workers.risk_jobs import assess_risk_job
from tests.integration.conftest import bearer
from tests.integration.test_disputes import dispute, drow, paid
from tests.integration.test_grading import make_admin
from tests.integration.test_listings import create
from tests.integration.test_matching_agent import buyer, farmer, mk
from tests.integration.test_payments import MP, deliver, start
from tests.integration.test_pricing_agent import seed_market

A = "/api/v1/admin"
GOOD_NOTE = "Reviewed the details with the party."


def settings(**over):
    return get_settings().model_copy(update=over)


async def run(db, event, kind, eid, llms=None, **over):
    return await FraudRiskAgent(db, settings(**over), llms or []).run(event, kind, str(eid))


async def anomalies(db, **where):
    stmt = select(AnomalyEvent).order_by(AnomalyEvent.detected_at, AnomalyEvent.id)
    for k, v in where.items():
        stmt = stmt.where(getattr(AnomalyEvent, k) == v)
    return list((await db.scalars(stmt.execution_options(populate_existing=True))).all())


async def audit_actions(db, entity_type):
    return [a.action for a in (await db.scalars(select(AuditLog).where(AuditLog.entity_type == entity_type).order_by(AuditLog.timestamp))).all()]


async def two_admins(db, client):
    a1 = await make_admin(db, client, "admin1@example.com")
    a2 = await make_admin(db, client, "admin2@example.com")
    return a1, a2


async def uid(db, email):
    return (await db.scalar(select(User.id).where(User.email == email)))


def risk_jobs(app_ctx):
    return [j for j in app_ctx.state.fake_queue.jobs if j[0] == "assess_risk_job"]


class LLM:
    name, available = "gemini", True

    def __init__(self, out=None, err=None):
        self.out, self.err = out, err

    async def complete_json(self, system, user):
        if self.err:
            raise LLMProviderError(self.err, self.name)
        return self.out


# ---------------------------------------------------------------- event -> job -> flag
async def test_listing_events_queue_tracked_idempotent_risk_jobs(app_ctx, client, db):
    t = await client.post("/api/v1/auth/register", json={"email": "f1@example.com", "password": "Sup3rSecret!", "full_name": "Ravi", "role": "FARMER"})
    h = bearer(t.json()["data"])
    d = await create(client, h)
    jobs = risk_jobs(app_ctx)
    assert len(jobs) == 1 and jobs[0][1][:3] == ("listing.created", "listing", d["id"])
    ex = await db.get(AgentExecution, uuid.UUID(jobs[0][1][3]))
    assert (ex.agent_name, ex.status, ex.trigger_type, ex.idempotency_key) == (
        AgentName.FRAUD_RISK, AgentStatus.QUEUED, "listing.created", f"risk:listing.created:{d['id']}")
    r = await client.patch(f"/api/v1/listings/{d['id']}", json={"base_price": 31}, headers=h)
    assert r.status_code == 200 and [j[1][0] for j in risk_jobs(app_ctx)] == ["listing.created", "listing.updated"]


async def test_price_deviation_is_flagged_once_notified_audited_and_never_called_fraud(app_ctx, client, db):
    await seed_market(db)
    admin = await make_admin(db, client)
    _, fid = await farmer(client, 1)
    lid = await mk(db, fid, price=500)  # Rs 5/kg vs ~Rs 30 market reference
    st = await run(db, "listing.created", "listing", lid)
    assert st["outcome"] == "flagged" and len(st["new_events"]) == 1
    [a] = await anomalies(db)
    assert (a.rule_id, a.severity, a.status, a.entity_type, a.entity_id) == (
        "PRICE_DEVIATION", AnomalySeverity.HIGH, AnomalyStatus.FLAGGED_FOR_REVIEW, "listing", str(lid))
    assert "fraud" not in (a.reason + a.recommended_action).lower() and a.details["subject_user_id"] == str(fid)
    assert a.details["deviation_pct"] < -80 and a.recommended_action
    notes = (await db.scalars(select(Notification).where(Notification.title == "Flagged for review"))).all()
    assert len(notes) == 1 and notes[0].data["anomaly_id"] == str(a.id)
    assert await audit_actions(db, "anomaly") == ["risk.flagged"]
    # replaying the same event is a no-op: no second flag, no second notification, no second audit row
    st2 = await run(db, "listing.created", "listing", lid)
    assert st2["new_events"] == [] and len(await anomalies(db)) == 1
    assert len((await db.scalars(select(Notification).where(Notification.title == "Flagged for review"))).all()) == 1
    assert (await client.get(f"{A}/anomalies/{a.id}", headers=admin)).json()["data"]["status"] == "FLAGGED_FOR_REVIEW"


async def test_normal_activity_creates_no_flag_and_job_reports_it(app_ctx, client, db):
    await seed_market(db)
    _, fid = await farmer(client, 1)
    lid = await mk(db, fid, price=3000)
    q = RecordingJobQueue()
    from app.agents.runtime import dispatch
    eid = await dispatch(db, q, agent=AgentName.FRAUD_RISK, job_name="assess_risk_job", trigger_type="listing.created", entity_type="listing",
                         entity_id=lid, job_args=("listing.created", "listing", str(lid)))
    await assess_risk_job({"llms": []}, "listing.created", "listing", str(lid), str(eid))
    ex = await db.get(AgentExecution, eid, populate_existing=True)
    assert (ex.status, ex.summary) == (AgentStatus.COMPLETED, "no risk signals") and await anomalies(db) == []
    assert [c["tool"] for c in ex.tool_calls] == ["collect_context", "risk_rules"]


async def test_flagged_run_marks_execution_review_required(app_ctx, client, db):
    await seed_market(db)
    await make_admin(db, client)
    _, fid = await farmer(client, 1)
    lid = await mk(db, fid, price=500)
    from app.agents.runtime import dispatch
    eid = await dispatch(db, RecordingJobQueue(), agent=AgentName.FRAUD_RISK, job_name="assess_risk_job", trigger_type="listing.created",
                         entity_type="listing", entity_id=lid, job_args=("listing.created", "listing", str(lid)))
    await assess_risk_job({"llms": []}, "listing.created", "listing", str(lid), str(eid))
    ex = await db.get(AgentExecution, eid, populate_existing=True)
    assert ex.status == AgentStatus.REVIEW_REQUIRED and "1 signal(s) flagged for review (1 new, highest HIGH)" == ex.summary
    assert ex.provider == "deterministic" and ex.fallback_used is False


async def test_missing_entities_and_bad_ids_are_skipped_safely(app_ctx, client, db):
    for kind, ev in (("listing", "listing.created"), ("order", "order.created"), ("payment", "payment.failed")):
        assert (await run(db, ev, kind, uuid.uuid4()))["outcome"] == "skipped"
    assert (await run(db, "listing.created", "listing", "not-a-uuid"))["outcome"] == "skipped"
    assert (await run(db, "order.created", "listing", uuid.uuid4()))["outcome"] == "skipped"  # event/entity mismatch
    assert await anomalies(db) == []


async def test_edit_burst_and_large_lot(app_ctx, client, db):
    await seed_market(db)
    t = await client.post("/api/v1/auth/register", json={"email": "f1@example.com", "password": "Sup3rSecret!", "full_name": "Ravi", "role": "FARMER"})
    h = bearer(t.json()["data"])
    d = await create(client, h)
    for p in (31, 32, 33, 34, 35):
        assert (await client.patch(f"/api/v1/listings/{d['id']}", json={"base_price": p}, headers=h)).status_code == 200
    await run(db, "listing.updated", "listing", d["id"])
    assert [(a.rule_id, a.severity) for a in await anomalies(db)] == [("LISTING_EDIT_BURST", AnomalySeverity.MEDIUM)]
    st = await run(db, "listing.updated", "listing", d["id"], RISK_LARGE_LOT_KG=100)
    assert {a.rule_id for a in await anomalies(db)} == {"LISTING_EDIT_BURST", "QUANTITY_PRICE_COMBINATION"} and len(st["new_events"]) == 1


async def test_duplicate_image_across_different_accounts(app_ctx, client, db):
    await make_admin(db, client)
    _, f1 = await farmer(client, 1)
    _, f2 = await farmer(client, 2)
    l1, l2, l3 = await mk(db, f1), await mk(db, f2), await mk(db, f1)
    sha = "ab" * 32
    for i, l in enumerate((l1, l2, l3)):
        db.add(ListingImage(listing_id=l, s3_key=f"k/{i}", content_type="image/jpeg", size_bytes=10, width=300, height=300, sha256=sha, is_primary=True))
    await db.commit()
    await run(db, "image.uploaded", "listing", l1)
    [a] = await anomalies(db)
    assert a.rule_id == "DUPLICATE_IMAGE" and a.details["other_listing_ids"] == [str(l2)]  # same-farmer reuse (l3) is not flagged


async def test_low_confidence_is_listed_but_does_not_ping_admins(app_ctx, client, db):
    await make_admin(db, client)
    _, fid = await farmer(client, 1)
    lid = await mk(db, fid, status=ListingStatus.REVIEW_REQUIRED)
    db.add(CropGradingResult(listing_id=lid, image_sha256="c" * 64, grade=Grade.B, confidence=0.3, defect_percentage=10, reason="blurry",
                             issues=[], provider=GradingProvider.GEMINI, requires_review=True))
    await db.commit()
    await run(db, "grading.completed", "listing", lid)
    [a] = await anomalies(db)
    assert (a.rule_id, a.severity) == ("LOW_AI_CONFIDENCE", AnomalySeverity.LOW)
    assert (await db.scalars(select(Notification).where(Notification.title == "Flagged for review"))).first() is None


async def test_failed_payment_event_triggers_risk_job_and_failures_are_counted(app_ctx, client, db):
    await make_admin(db, client)
    c = await start(client, db)
    app_ctx.state.fake_queue.jobs.clear()
    f = MP.payment_event("failed", provider_order_id=c["po"], amount_paise=1425000, reason="Insufficient funds")
    assert (await deliver(client, app_ctx, f)).json()["status"] == "applied"
    [(name, args)] = risk_jobs(app_ctx)
    assert args[:3] == ("payment.failed", "payment", c["pid"])
    assert (await run(db, "payment.failed", "payment", c["pid"]))["signals"] == []  # 1 failure < threshold
    st = await run(db, "payment.failed", "payment", c["pid"], RISK_PAYMENT_FAILURES_24H=1)
    [a] = await anomalies(db)
    assert a.rule_id == "REPEATED_PAYMENT_FAILURES" and a.severity == AnomalySeverity.MEDIUM and a.details["failures_24h"] == 1
    assert a.details["subject_user_id"] == str(c["b1"]) and len(st["new_events"]) == 1
    dup = await deliver(client, app_ctx, f, event_id="evt_same")  # a duplicate delivery must not queue another job
    again = await deliver(client, app_ctx, f, event_id="evt_same")
    assert again.json()["status"] == "duplicate" and dup.status_code == 200


async def test_new_account_large_order_and_order_event(app_ctx, client, db):
    await make_admin(db, client)
    app_ctx.state.fake_queue.jobs.clear()
    from tests.integration.test_payments import setup
    c = await setup(client, db)
    [(name, args)] = risk_jobs(app_ctx)
    assert args[:3] == ("order.created", "order", c["oid"])
    assert (await run(db, "order.created", "order", c["oid"]))["signals"] == []  # Rs 14,250 is below the Rs 1,00,000 default
    await run(db, "order.created", "order", c["oid"], RISK_NEW_ACCOUNT_ORDER_PAISE=1000)
    [a] = await anomalies(db)
    assert a.rule_id == "NEW_ACCOUNT_LARGE_ORDER" and a.entity_id == c["oid"] and a.details["subject_user_id"] == str(c["b1"])


# ---------------------------------------------------------------- AI assist is advisory only
async def test_ai_summary_is_attached_only_when_valid_and_never_changes_classification(app_ctx, client, db):
    await seed_market(db)
    await make_admin(db, client)
    _, fid = await farmer(client, 1)
    good = LLM(json.dumps({"summary": "The listed price is far below the market reference and is worth a quick review."}))
    lid = await mk(db, fid, price=500)
    st = await run(db, "listing.created", "listing", lid, [good])
    [a] = await anomalies(db)
    assert a.details["ai_summary"]["provider"] == "gemini" and a.severity == AnomalySeverity.HIGH and st["degraded"] is False
    # accusatory / invented numbers are discarded; the deterministic flag still exists
    for bad in ('{"summary": "This farmer is committing fraud with prices."}', '{"summary": "Price is 77777 below normal, investigate it."}', "not json"):
        lid2 = await mk(db, fid, price=500, crop="Tomato", qty=801)
        await run(db, "listing.created", "listing", lid2, [LLM(bad)])
        a2 = [x for x in await anomalies(db, entity_id=str(lid2))][0]
        assert "ai_summary" not in a2.details and a2.status == AnomalyStatus.FLAGGED_FOR_REVIEW
    lid3 = await mk(db, fid, price=500, qty=802)
    st = await run(db, "listing.created", "listing", lid3, [LLM(err="timeout")])
    assert st["degraded"] is True and len(await anomalies(db, entity_id=str(lid3))) == 1


# ---------------------------------------------------------------- admin API
async def seeded_flags(db, client):
    await seed_market(db)
    _, fid = await farmer(client, 1)
    ids = []
    for qty, price in ((801, 500), (802, 1500), (803, 5500)):
        lid = await mk(db, fid, qty=qty, price=price)
        await run(db, "listing.created", "listing", lid)
        ids.append(lid)
    return fid, ids


async def test_anomaly_list_filters_pagination_and_access(app_ctx, client, db):
    a1, _ = await two_admins(db, client)
    fid, _ = await seeded_flags(db, client)
    d = (await client.get(f"{A}/anomalies", headers=a1)).json()["data"]
    assert len(d["items"]) == 3 and d["open_count"] == 3
    assert sorted(i["severity"] for i in d["items"]) == ["HIGH", "HIGH", "MEDIUM"]
    assert {i["status"] for i in d["items"]} == {"FLAGGED_FOR_REVIEW"} and all(i["recommended_action"] and i["detected_at"] for i in d["items"])
    p1 = (await client.get(f"{A}/anomalies?limit=2", headers=a1)).json()["data"]
    p2 = (await client.get(f"{A}/anomalies?limit=2&cursor={p1['next_cursor']}", headers=a1)).json()["data"]
    assert len(p1["items"]) == 2 and len(p2["items"]) == 1 and p2["next_cursor"] is None
    assert len((await client.get(f"{A}/anomalies?severity=MEDIUM", headers=a1)).json()["data"]["items"]) == 1
    assert (await client.get(f"{A}/anomalies?status=DISMISSED", headers=a1)).json()["data"]["items"] == []
    assert (await client.get(f"{A}/anomalies?severity=BOGUS", headers=a1)).status_code == 422
    fh, _ = await farmer(client, 9)
    assert (await client.get(f"{A}/anomalies", headers=fh)).status_code == 403  # not even the farmer who is the subject
    assert (await client.get(f"{A}/anomalies")).status_code == 401
    assert (await client.get(f"{A}/anomalies/{uuid.uuid4()}", headers=a1)).status_code == 404


async def test_dismiss_resolve_and_state_machine(app_ctx, client, db):
    a1, _ = await two_admins(db, client)
    _, ids = await seeded_flags(db, client)
    fl = (await anomalies(db))
    x, y = fl[0], fl[1]
    assert (await client.post(f"{A}/anomalies/{x.id}/dismiss", json={"note": "no"}, headers=a1)).status_code == 422  # note required (>=5)
    r = await client.post(f"{A}/anomalies/{x.id}/dismiss", json={"note": "Price is intentional, farmer confirmed."}, headers=a1)
    d = r.json()["data"]
    assert r.status_code == 200 and d["status"] == "DISMISSED" and d["reviewed_by"] and d["review_note"].startswith("Price is")
    assert (await client.post(f"{A}/anomalies/{x.id}/resolve", json={"note": GOOD_NOTE}, headers=a1)).status_code == 409  # terminal
    assert (await client.post(f"{A}/anomalies/{y.id}/resolve", json={"note": GOOD_NOTE}, headers=a1)).json()["data"]["status"] == "RESOLVED"
    assert (await client.get(f"{A}/anomalies", headers=a1)).json()["data"]["open_count"] == 1
    assert await audit_actions(db, "anomaly") == ["risk.flagged"] * 3 + ["anomaly.dismissed", "anomaly.resolved"]
    ex = (await db.scalars(select(AuditLog).where(AuditLog.action == "anomaly.dismissed"))).one()
    assert ex.previous_state == {"status": "FLAGGED_FOR_REVIEW"} and ex.new_state == {"status": "DISMISSED"}


async def test_manual_assess_endpoint_queues_a_job(app_ctx, client, db):
    a1, _ = await two_admins(db, client)
    _, fid = await farmer(client, 1)
    lid = await mk(db, fid)
    r = await client.post(f"{A}/risk/assess", json={"entity_type": "listing", "entity_id": str(lid)}, headers=a1)
    assert r.status_code == 202
    ex = await db.get(AgentExecution, uuid.UUID(r.json()["data"]["jobId"]))
    assert ex.agent_name == AgentName.FRAUD_RISK and risk_jobs(app_ctx)[-1][1][:3] == ("listing.updated", "listing", str(lid))
    assert (await client.post(f"{A}/risk/assess", json={"entity_type": "user", "entity_id": str(lid)}, headers=a1)).status_code == 422


# ---------------------------------------------------------------- human approval
async def req(client, h, action_type, payload):
    return await client.post(f"{A}/pending-actions", json={"action_type": action_type, "payload": payload}, headers=h)


async def test_ban_requires_a_second_admin_and_executes_only_on_approval(app_ctx, client, db):
    a1, a2 = await two_admins(db, client)
    fh, fid = await farmer(client, 1)
    r = await req(client, a1, "BAN_USER", {"user_id": str(fid), "reason": "Repeated abusive listings reported by buyers."})
    d = r.json()["data"]
    assert r.status_code == 201 and d["status"] == "PENDING" and d["entity_type"] == "user" and d["requested_via"] == "admin"
    assert (await db.get(User, fid, populate_existing=True)).is_active is True  # requesting executes NOTHING
    assert (await client.get("/api/v1/auth/me", headers=fh)).status_code == 200
    # four-eyes
    r = await client.post(f"{A}/pending-actions/{d['id']}/approve", json={"reason": GOOD_NOTE}, headers=a1)
    assert r.status_code == 403
    assert (await db.get(User, fid, populate_existing=True)).is_active is True
    # duplicate request while one is pending
    assert (await req(client, a2, "BAN_USER", {"user_id": str(fid), "reason": "Another reason entirely here."})).status_code == 409
    r = await client.post(f"{A}/pending-actions/{d['id']}/approve", json={"reason": "Evidence confirmed by two reports."}, headers=a2)
    out = r.json()["data"]
    assert r.status_code == 200 and out["status"] == "EXECUTED" and out["result"] == {"user_id": str(fid), "is_active": False}
    assert out["decided_by"] and out["executed_at"] and out["decision_reason"].startswith("Evidence")
    u = await db.get(User, fid, populate_existing=True)
    assert u.is_active is False and u.banned_at and u.ban_reason.startswith("Repeated")
    assert (await client.get("/api/v1/auth/me", headers=fh)).status_code in (401, 403)  # the live token stops working immediately
    login = await client.post("/api/v1/auth/login", json={"email": "farmer1@example.com", "password": "Sup3rSecret!"})
    assert login.status_code == 403
    assert await audit_actions(db, "pending_action") == ["pending_action.requested", "pending_action.approved", "pending_action.executed"]
    assert "user.banned" in await audit_actions(db, "user")
    # deciding twice
    assert (await client.post(f"{A}/pending-actions/{d['id']}/approve", json={"reason": GOOD_NOTE}, headers=a2)).status_code == 409
    assert (await client.post(f"{A}/pending-actions/{d['id']}/reject", json={"reason": GOOD_NOTE}, headers=a2)).status_code == 409


async def test_reject_leaves_everything_untouched_and_needs_a_reason(app_ctx, client, db):
    a1, a2 = await two_admins(db, client)
    _, fid = await farmer(client, 1)
    d = (await req(client, a1, "BAN_USER", {"user_id": str(fid), "reason": "Suspicious account activity noticed."})).json()["data"]
    assert (await client.post(f"{A}/pending-actions/{d['id']}/reject", json={}, headers=a2)).status_code == 422
    r = await client.post(f"{A}/pending-actions/{d['id']}/reject", json={"reason": "Insufficient evidence for a ban."}, headers=a2)
    assert r.json()["data"]["status"] == "REJECTED" and r.json()["data"]["executed_at"] is None
    assert (await db.get(User, fid, populate_existing=True)).is_active is True
    again = await req(client, a2, "BAN_USER", {"user_id": str(fid), "reason": "New evidence has been provided."})
    assert again.status_code == 201  # a rejected request does not block a fresh one


async def test_request_validation_and_protected_targets(app_ctx, client, db, demo_users):
    a1, a2 = await two_admins(db, client)
    fh, fid = await farmer(client, 1)
    a2id = await uid(db, "admin2@example.com")
    assert (await req(client, a1, "BAN_USER", {"user_id": str(a2id), "reason": "Trying to ban another admin."})).status_code == 409
    assert (await req(client, a1, "BAN_USER", {"user_id": str(demo_users["farmer"].id), "reason": "Demo accounts are protected."})).status_code == 409
    assert (await req(client, a1, "BAN_USER", {"user_id": str(uuid.uuid4()), "reason": "Nobody with this id exists."})).status_code == 404
    assert (await req(client, a1, "BAN_USER", {"user_id": str(fid)})).status_code == 422  # reason missing
    assert (await req(client, a1, "BAN_USER", {"user_id": str(fid), "reason": "Valid reason here.", "role": "ADMIN"})).status_code == 422
    assert (await req(client, a1, "DROP_DATABASE", {})).status_code == 422
    assert (await req(client, fh, "BAN_USER", {"user_id": str(fid), "reason": "Farmers cannot do this call."})).status_code == 403
    assert (await client.get(f"{A}/pending-actions", headers=fh)).status_code == 403
    assert await db.scalar(select(PendingAction.id).limit(1)) is None


async def test_demo_admin_can_look_but_not_decide(app_ctx, client, db, demo_users):
    a1, _ = await two_admins(db, client)
    _, fid = await farmer(client, 1)
    d = (await req(client, a1, "BAN_USER", {"user_id": str(fid), "reason": "Pending review by another admin."})).json()["data"]
    demo = bearer((await client.post("/api/v1/auth/demo", json={"kind": "admin"})).json()["data"])
    assert (await client.get(f"{A}/pending-actions", headers=demo)).status_code == 200
    assert (await client.get(f"{A}/anomalies", headers=demo)).status_code == 200
    assert (await client.post(f"{A}/pending-actions/{d['id']}/approve", json={"reason": GOOD_NOTE}, headers=demo)).status_code == 403
    assert (await client.post(f"{A}/pending-actions/{d['id']}/reject", json={"reason": GOOD_NOTE}, headers=demo)).status_code == 403
    assert (await db.get(User, fid, populate_existing=True)).is_active is True


async def test_pending_list_filters_and_pagination(app_ctx, client, db):
    a1, a2 = await two_admins(db, client)
    ids = []
    for n in range(1, 4):
        _, fid = await farmer(client, n)
        ids.append((await req(client, a1, "BAN_USER", {"user_id": str(fid), "reason": f"Reason number {n} for review."})).json()["data"]["id"])
    await client.post(f"{A}/pending-actions/{ids[0]}/reject", json={"reason": GOOD_NOTE}, headers=a2)
    d = (await client.get(f"{A}/pending-actions?status=PENDING", headers=a1)).json()["data"]
    assert len(d["items"]) == 2 and d["pending_count"] == 2
    p1 = (await client.get(f"{A}/pending-actions?limit=2", headers=a1)).json()["data"]
    p2 = (await client.get(f"{A}/pending-actions?limit=2&cursor={p1['next_cursor']}", headers=a1)).json()["data"]
    assert len(p1["items"]) == 2 and len(p2["items"]) == 1
    assert (await client.get(f"{A}/pending-actions/{ids[1]}", headers=a1)).json()["data"]["status"] == "PENDING"
    assert (await client.get(f"{A}/pending-actions/{uuid.uuid4()}", headers=a1)).status_code == 404


async def test_agent_proposal_flow_from_high_signal_to_approved_ban(app_ctx, client, db):
    """HIGH signal -> agent QUEUES a BAN_USER request (never bans) -> admin approves -> executed -> anomaly resolved."""
    await seed_market(db)
    a1 = await make_admin(db, client)
    fh, fid = await farmer(client, 1)
    lid = await mk(db, fid, price=500)
    st = await run(db, "listing.created", "listing", lid, RISK_PROPOSE_BAN_ON_HIGH=True)
    [a] = await anomalies(db)
    [pa] = (await db.scalars(select(PendingAction))).all()
    assert (pa.action_type, pa.status, pa.requested_via, pa.requested_by, pa.entity_id) == (
        PendingActionType.BAN_USER, PendingActionStatus.PENDING, "agent", None, str(fid))
    assert pa.payload["anomaly_id"] == str(a.id) and len(st["new_events"]) == 1
    assert (await db.get(User, fid, populate_existing=True)).is_active is True and a.status == AnomalyStatus.ACTION_REQUESTED
    # re-running does not queue a second proposal
    await run(db, "listing.created", "listing", lid, RISK_PROPOSE_BAN_ON_HIGH=True)
    assert len((await db.scalars(select(PendingAction))).all()) == 1
    r = await client.post(f"{A}/pending-actions/{pa.id}/approve", json={"reason": "Reviewed listing history; ban justified."}, headers=a1)
    assert r.json()["data"]["status"] == "EXECUTED"  # agent-created => any admin may decide
    assert (await anomalies(db))[0].status == AnomalyStatus.RESOLVED
    assert (await client.get("/api/v1/auth/me", headers=fh)).status_code in (401, 403)


async def test_default_config_never_proposes_actions(app_ctx, client, db):
    await seed_market(db)
    await make_admin(db, client)
    _, fid = await farmer(client, 1)
    await run(db, "listing.created", "listing", await mk(db, fid, price=500))
    assert (await db.scalars(select(PendingAction))).first() is None and len(await anomalies(db)) == 1


async def test_request_action_from_an_anomaly_and_rejection_reopens_it(app_ctx, client, db):
    a1, a2 = await two_admins(db, client)
    fid, _ = await seeded_flags(db, client)
    [x, *_] = await anomalies(db)
    r = await client.post(f"{A}/anomalies/{x.id}/request-action", headers=a1,
                          json={"action_type": "BAN_USER", "payload": {"user_id": str(fid), "reason": "Escalating after repeated flags."}})
    pa = r.json()["data"]
    assert r.status_code == 201 and pa["payload"]["anomaly_id"] == str(x.id)
    assert (await client.get(f"{A}/anomalies/{x.id}", headers=a1)).json()["data"]["status"] == "ACTION_REQUESTED"
    assert (await client.post(f"{A}/anomalies/{x.id}/dismiss", json={"note": GOOD_NOTE}, headers=a1)).status_code == 409  # waiting on approval
    await client.post(f"{A}/pending-actions/{pa['id']}/reject", json={"reason": "Not enough to justify a ban."}, headers=a2)
    assert (await client.get(f"{A}/anomalies/{x.id}", headers=a1)).json()["data"]["status"] == "FLAGGED_FOR_REVIEW"
    assert (await client.post(f"{A}/anomalies/{x.id}/dismiss", json={"note": GOOD_NOTE}, headers=a1)).status_code == 200


async def test_approve_low_confidence_grade_executes_the_normal_review_path(app_ctx, client, db):
    a1, a2 = await two_admins(db, client)
    _, fid = await farmer(client, 1)
    lid = await mk(db, fid, status=ListingStatus.REVIEW_REQUIRED)
    db.add(CropGradingResult(listing_id=lid, image_sha256="d" * 64, grade=Grade.B, confidence=0.4, defect_percentage=10, reason="dim",
                             issues=[], provider=GradingProvider.GEMINI, requires_review=True))
    await db.commit()
    d = (await req(client, a1, "APPROVE_LOW_CONFIDENCE_GRADE", {"listing_id": str(lid), "reason": "Photo is dim but produce looks fine."})).json()["data"]
    assert (await db.get(Listing, lid, populate_existing=True)).status == ListingStatus.REVIEW_REQUIRED
    out = (await client.post(f"{A}/pending-actions/{d['id']}/approve", json={"reason": "Second check agrees with the grade."}, headers=a2)).json()["data"]
    assert out["status"] == "EXECUTED" and out["result"] == {"listing_id": str(lid), "status": "ACTIVE"}
    assert (await db.get(Listing, lid, populate_existing=True)).status == ListingStatus.ACTIVE
    assert "grading.review_approved" in await audit_actions(db, "listing")
    # not REVIEW_REQUIRED any more => cannot even be requested
    assert (await req(client, a1, "APPROVE_LOW_CONFIDENCE_GRADE", {"listing_id": str(lid), "reason": "Trying again after approval."})).status_code == 409


async def test_execution_failure_is_recorded_not_hidden(app_ctx, client, db):
    a1, a2 = await two_admins(db, client)
    _, fid = await farmer(client, 1)
    lid = await mk(db, fid, status=ListingStatus.REVIEW_REQUIRED)
    db.add(CropGradingResult(listing_id=lid, image_sha256="e" * 64, grade=Grade.B, confidence=0.4, defect_percentage=10, reason="dim",
                             issues=[], provider=GradingProvider.GEMINI, requires_review=True))
    await db.commit()
    d = (await req(client, a1, "APPROVE_LOW_CONFIDENCE_GRADE", {"listing_id": str(lid), "reason": "Looks acceptable to me."})).json()["data"]
    l = await db.get(Listing, lid, populate_existing=True)
    l.status = ListingStatus.ARCHIVED  # state changed while the request waited
    await db.commit()
    out = (await client.post(f"{A}/pending-actions/{d['id']}/approve", json={"reason": GOOD_NOTE}, headers=a2)).json()["data"]
    assert out["status"] == "FAILED" and out["result"]["error"] == "conflict" and out["executed_at"]
    assert (await db.get(Listing, lid, populate_existing=True)).status == ListingStatus.ARCHIVED
    assert (await audit_actions(db, "pending_action"))[-1] == "pending_action.failed"
    assert (await client.post(f"{A}/pending-actions/{d['id']}/approve", json={"reason": GOOD_NOTE}, headers=a2)).status_code == 409


async def test_resolve_serious_dispute_via_approval(app_ctx, client, db):
    a1, a2 = await two_admins(db, client)
    c = await paid(client, app_ctx, db)
    did = (await dispute(client, c)).json()["data"]["id"]
    d = (await req(client, a1, "RESOLVE_SERIOUS_DISPUTE", {"dispute_id": did, "outcome": "SELLER_FAVOURED",
                                                           "resolution": "Delivery proof shows goods arrived intact."})).json()["data"]
    assert (await drow(db, did)).status == DisputeStatus.OPEN
    out = (await client.post(f"{A}/pending-actions/{d['id']}/approve", json={"reason": "Evidence reviewed by second admin."}, headers=a2)).json()["data"]
    assert out["status"] == "EXECUTED" and out["result"]["status"] == "RESOLVED"
    assert (await drow(db, did)).status == DisputeStatus.RESOLVED
    from tests.integration.test_orders import order_row
    assert (await order_row(db, c["oid"])).status == OrderStatus.COMPLETED
    assert "dispute.resolved" in await audit_actions(db, "dispute")
    assert (await req(client, a1, "RESOLVE_SERIOUS_DISPUTE", {"dispute_id": did, "outcome": "BUYER_REFUND", "resolution": "Changed my mind."})).status_code == 409
