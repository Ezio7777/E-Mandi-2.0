"""Stage 18: recovery sweepers + worker settings. Real Postgres/Redis; time is aged by editing timestamps."""
import json
import uuid
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.models.agent_execution import AgentExecution
from app.models.audit_log import AuditLog
from app.models.buyer_requirement import BuyerRequirement
from app.models.enums import (
    AgentName,
    AgentStatus,
    ListingStatus,
    OrderStatus,
    PaymentStatus,
    PendingActionStatus,
    PendingActionType,
    RequirementStatus,
)
from app.models.idempotency_key import IdempotencyKey
from app.models.listing import Listing
from app.models.listing_image import ListingImage
from app.models.notification import Notification
from app.models.order import Order
from app.models.otp_challenge import OtpChallenge
from app.models.payment import Payment
from app.models.payment_event import PaymentEvent
from app.models.pending_action import PendingAction
from app.services.recovery import RecoveryService, read_worker_status
from app.workers.maintenance_jobs import SWEEPERS, run_sweeper, worker_heartbeat_job
from app.workers.queue import RecordingJobQueue
from app.workers.settings import WorkerSettings
from sqlalchemy import select, update

from tests.integration.conftest import FakeStorage
from tests.integration.test_grading import make_admin
from tests.integration.test_matching_agent import buyer, farmer, mk
from tests.integration.test_payments import captured, start

OLD = datetime.now(UTC) - timedelta(hours=48)


def svc(redis, queue=None, storage=None, provider=None, **over):
    s = get_settings().model_copy(update=over)
    return RecoveryService(get_sessionmaker(), s, queue or RecordingJobQueue(), redis, storage, provider)


async def age(db, model, row_id, **cols):
    await db.execute(update(model).where(model.id == row_id).values(**cols))
    await db.commit()


async def mk_exec(db, agent, status=AgentStatus.QUEUED, entity="listing", eid=None, key=None, trigger="t", created=OLD, started=None):
    ex = AgentExecution(agent_name=agent, trigger_type=trigger, status=status, idempotency_key=key, related_entity_type=entity,
                        related_entity_id=str(eid or uuid.uuid4()), attempt=0, fallback_used=False, tool_calls=[], created_at=created,
                        started_at=started)
    db.add(ex)
    await db.commit()
    return ex.id


async def fresh(db, model, row_id):
    return await db.get(model, row_id, populate_existing=True)


# ------------------------------------------------------------------ stuck executions
async def test_queued_executions_are_requeued_with_correct_job_args(app_ctx, client, db, redis):
    _, fid = await farmer(client, 1)
    lid, rid = uuid.uuid4(), uuid.uuid4()
    grade = await mk_exec(db, AgentName.CROP_GRADING, eid=lid)
    price = await mk_exec(db, AgentName.SMART_PRICING, eid=lid, key="pricing:abc-123")
    match = await mk_exec(db, AgentName.BUYER_MATCHING, entity="requirement", eid=rid)
    risk = await mk_exec(db, AgentName.FRAUD_RISK, eid=lid, trigger="listing.created")
    q = RecordingJobQueue()
    out = await svc(redis, q).recover_executions()
    assert out["requeued"] == 4
    jobs = {n: a for n, a in q.jobs}
    assert jobs["grade_listing_job"] == (str(lid), str(grade))
    assert jobs["price_listing_job"] == (str(lid), "abc-123", str(price))
    assert jobs["match_requirement_job"] == (str(rid), str(match))
    assert jobs["assess_risk_job"] == ("listing.created", "listing", str(lid), str(risk))


async def test_recent_and_finished_executions_are_left_alone(app_ctx, db, redis):
    await mk_exec(db, AgentName.CROP_GRADING, created=datetime.now(UTC))
    await mk_exec(db, AgentName.CROP_GRADING, status=AgentStatus.COMPLETED)
    await mk_exec(db, AgentName.CROP_GRADING, status=AgentStatus.RUNNING, created=OLD, started=datetime.now(UTC))
    q = RecordingJobQueue()
    assert (await svc(redis, q).recover_executions())["requeued"] == 0
    assert q.jobs == []


async def test_stale_running_execution_is_recovered(app_ctx, db, redis):
    ex = await mk_exec(db, AgentName.BUYER_MATCHING, status=AgentStatus.RUNNING, entity="requirement", started=OLD)
    q = RecordingJobQueue()
    assert (await svc(redis, q).recover_executions())["requeued"] == 1
    assert (await fresh(db, AgentExecution, ex)).status == AgentStatus.QUEUED


async def test_cooldown_prevents_repeated_requeue_and_cap_fails_execution(app_ctx, db, redis):
    ex = await mk_exec(db, AgentName.BUYER_MATCHING, entity="requirement")
    q = RecordingJobQueue()
    s = svc(redis, q)
    assert (await s.recover_executions())["requeued"] == 1
    assert (await s.recover_executions())["skipped"] == 1  # cooldown
    assert len(q.jobs) == 1
    for _ in range(3):  # drop the cooldown to simulate time passing
        await redis.delete(f"recover:cool:exec:{ex}")
        await s.recover_executions()
    row = await fresh(db, AgentExecution, ex)
    assert row.status == AgentStatus.FAILED and row.error_code == "recovery_exhausted"
    assert len(q.jobs) == 3


async def test_voice_execution_is_abandoned_not_rerun(app_ctx, db, redis):
    ex = await mk_exec(db, AgentName.VOICE_ASSISTANT, status=AgentStatus.RUNNING, entity="session", started=OLD)
    q = RecordingJobQueue()
    out = await svc(redis, q).recover_executions()
    assert out["failed"] == 1 and q.jobs == []
    assert (await fresh(db, AgentExecution, ex)).error_code == "abandoned"


async def test_exhausted_grading_execution_routes_listing_to_review(app_ctx, client, db, redis):
    _, fid = await farmer(client, 1)
    lid = await mk(db, fid, status=ListingStatus.ANALYZING)
    ex = await mk_exec(db, AgentName.CROP_GRADING, eid=lid)
    await redis.set(f"recover:count:exec:{ex}", 3)
    await svc(redis).recover_executions()
    assert (await fresh(db, Listing, lid)).status == ListingStatus.REVIEW_REQUIRED
    assert (await fresh(db, AgentExecution, ex)).status == AgentStatus.FAILED


async def test_enqueue_failure_during_recovery_is_contained(app_ctx, db, redis):
    class Broken:
        async def enqueue(self, *a, **k):
            raise ConnectionError("redis down")
    await mk_exec(db, AgentName.BUYER_MATCHING, entity="requirement")
    out = await svc(redis, Broken()).recover_executions()
    assert out["requeued"] == 0 and out["skipped"] == 1


# ------------------------------------------------------------------ analyzing listings
async def test_stuck_analyzing_listing_gets_new_grading_run_then_review(app_ctx, client, db, redis):
    _, fid = await farmer(client, 1)
    lid = await mk(db, fid, status=ListingStatus.ANALYZING)
    await age(db, Listing, lid, updated_at=OLD)
    q = RecordingJobQueue()
    s = svc(redis, q)
    assert (await s.recover_analyzing())["requeued"] == 1
    name, args = q.jobs[0]
    assert name == "grade_listing_job" and args[0] == str(lid)
    ex = (await db.scalars(select(AgentExecution).where(AgentExecution.related_entity_id == str(lid)))).one()
    assert ex.trigger_type == "listing.analysis_recovery"
    assert (await s.recover_analyzing())["requeued"] == 0  # now has an in-flight execution
    await db.execute(update(AgentExecution).values(status=AgentStatus.FAILED))
    await db.commit()
    for _ in range(3):
        await s.recover_analyzing()
        await db.execute(update(AgentExecution).values(status=AgentStatus.FAILED))
        await db.commit()
    assert (await fresh(db, Listing, lid)).status == ListingStatus.REVIEW_REQUIRED


async def test_fresh_analyzing_listing_is_not_touched(app_ctx, client, db, redis):
    _, fid = await farmer(client, 1)
    await mk(db, fid, status=ListingStatus.ANALYZING)
    q = RecordingJobQueue()
    assert (await svc(redis, q).recover_analyzing())["requeued"] == 0


# ------------------------------------------------------------------ webhooks
async def test_unprocessed_webhook_is_reapplied_once(app_ctx, client, db, redis):
    c = await start(client, db)
    ev = app_ctx.state.fake_provider.parse_webhook(captured(c), "evt_stuck_1")
    db.add(PaymentEvent(provider="mock", provider_event_id="evt_stuck_1", event_type=ev.type, payload=ev.normalized(), created_at=OLD))
    await db.commit()
    s = svc(redis, provider=app_ctx.state.fake_provider)
    assert (await s.reprocess_webhooks())["applied"] == 1
    p = await fresh(db, Payment, uuid.UUID(c["pid"]))
    assert p.status == PaymentStatus.SUCCESS
    assert (await fresh(db, Order, uuid.UUID(c["oid"]))).status == OrderStatus.PAID
    assert (await s.reprocess_webhooks())["applied"] == 0  # processed_at now set
    row = await db.scalar(select(PaymentEvent).where(PaymentEvent.provider_event_id == "evt_stuck_1").execution_options(populate_existing=True))
    assert row.processed_at is not None and row.payload["outcome"] == "applied"


async def test_recent_unprocessed_webhook_is_left_for_the_request_path(app_ctx, client, db, redis):
    c = await start(client, db)
    ev = app_ctx.state.fake_provider.parse_webhook(captured(c), "evt_recent")
    db.add(PaymentEvent(provider="mock", provider_event_id="evt_recent", event_type=ev.type, payload=ev.normalized()))
    await db.commit()
    assert (await svc(redis, provider=app_ctx.state.fake_provider).reprocess_webhooks())["applied"] == 0


async def test_webhook_with_amount_mismatch_is_rejected_on_reapply(app_ctx, client, db, redis):
    c = await start(client, db)
    ev = app_ctx.state.fake_provider.parse_webhook(captured(c, amount=100), "evt_bad_amt")
    db.add(PaymentEvent(provider="mock", provider_event_id="evt_bad_amt", event_type=ev.type, payload=ev.normalized(), created_at=OLD))
    await db.commit()
    await svc(redis, provider=app_ctx.state.fake_provider).reprocess_webhooks()
    assert (await fresh(db, Payment, uuid.UUID(c["pid"]))).status != PaymentStatus.SUCCESS


# ------------------------------------------------------------------ cleanup
async def test_cleanup_deletes_only_expired_rows(app_ctx, client, db, redis):
    _, fid = await farmer(client, 1)
    now = datetime.now(UTC)
    for i, exp in enumerate([now - timedelta(hours=1), now + timedelta(hours=1)]):
        db.add(IdempotencyKey(user_id=fid, scope="orders", key=f"k{i}", request_hash="h", expires_at=exp))
    db.add(OtpChallenge(phone="+911", code_hash="x", expires_at=now - timedelta(days=3)))
    db.add(OtpChallenge(phone="+912", code_hash="x", expires_at=now - timedelta(minutes=1)))  # recently expired: kept 1 day
    await db.commit()
    out = await svc(redis).cleanup_expired()
    assert out["idempotency_keys"] == 1 and out["otp_challenges"] == 1
    keys = (await db.scalars(select(IdempotencyKey.key))).all()
    assert keys == ["k1"]
    assert await svc(redis).cleanup_expired() == {"idempotency_keys": 0, "otp_challenges": 0, "sessions": 0}


# ------------------------------------------------------------------ orphan S3
async def test_orphan_sweeper_deletes_only_old_unreferenced_images(app_ctx, client, db, redis):
    _, fid = await farmer(client, 1)
    lid = await mk(db, fid)
    root = f"e-mandi/listings/{lid}"
    kept, orphan, fresh_orphan = f"{root}/{uuid.uuid4()}.jpg", f"{root}/{uuid.uuid4()}.jpg", f"{root}/{uuid.uuid4()}.jpg"
    foreign = "other-app/listings/x/y.jpg"
    st = FakeStorage()
    for k in (kept, orphan, fresh_orphan, foreign):
        st.put(k, b"x")
    for k in (kept, orphan, foreign):
        st.modified[k] = OLD
    db.add(ListingImage(listing_id=lid, s3_key=kept, content_type="image/jpeg", size_bytes=1, width=10, height=10, sha256="a" * 64,
                        is_primary=True))
    await db.commit()
    out = await svc(redis, storage=st).sweep_orphan_images()
    assert out["deleted"] == 1
    assert set(st.objects) == {kept, fresh_orphan, foreign}


async def test_orphan_sweeper_respects_delete_cap(app_ctx, client, db, redis):
    _, fid = await farmer(client, 1)
    lid = await mk(db, fid)
    st = FakeStorage()
    for i in range(5):
        k = f"e-mandi/listings/{lid}/{uuid.uuid4()}.jpg"
        st.put(k, b"x")
        st.modified[k] = OLD
    out = await svc(redis, storage=st, ORPHAN_S3_MAX_DELETES=2).sweep_orphan_images()
    assert out["deleted"] == 2 and len(st.objects) == 3


async def test_orphan_sweeper_deletes_nothing_when_db_fails(app_ctx, db, redis):
    st = FakeStorage()
    k = f"e-mandi/listings/{uuid.uuid4()}/{uuid.uuid4()}.jpg"
    st.put(k, b"x")
    st.modified[k] = OLD

    class DeadSM:
        def __call__(self):
            raise ConnectionError("db down")
    s = svc(redis, storage=st)
    s.sm = DeadSM()  # type: ignore[assignment]
    try:
        await s.sweep_orphan_images()
    except ConnectionError:
        pass
    assert k in st.objects


# ------------------------------------------------------------------ rematch
async def req(db, bid, crop="Tomato", **kw):
    r = BuyerRequirement(buyer_id=bid, crop_name=crop, quantity_kg=100, location="Bengaluru", max_price_paise=5000, **kw)
    db.add(r)
    await db.commit()
    return r.id


async def test_rematch_triggers_only_when_a_newer_listing_appears(app_ctx, client, db, redis):
    _, fid = await farmer(client, 1)
    _, bid = await buyer(client, 1)
    rid = await req(db, bid)
    q = RecordingJobQueue()
    s = svc(redis, q)
    assert (await s.rematch_requirements())["rematched"] == 0  # no listings
    await mk(db, fid, crop="tomato")
    assert (await s.rematch_requirements())["rematched"] == 1
    assert q.jobs[0][0] == "match_requirement_job" and q.jobs[0][1][0] == str(rid)
    await db.execute(update(AgentExecution).values(status=AgentStatus.COMPLETED))
    await db.commit()
    assert (await s.rematch_requirements())["rematched"] == 0  # no listing newer than the last run


async def test_rematch_ignores_other_crops_inactive_listings_and_closed_requirements(app_ctx, client, db, redis):
    _, fid = await farmer(client, 1)
    _, bid = await buyer(client, 1)
    await req(db, bid, crop="Onion")
    await req(db, bid, crop="Tomato", status=RequirementStatus.CANCELLED)
    await mk(db, fid, crop="Tomato", status=ListingStatus.DRAFT)
    await mk(db, fid, crop="Potato")
    q = RecordingJobQueue()
    assert (await svc(redis, q).rematch_requirements())["rematched"] == 0


# ------------------------------------------------------------------ interrupted approved actions
async def test_approved_action_stuck_is_failed_and_admins_notified(app_ctx, client, db, redis):
    await make_admin(db, client, "admin1@example.com")
    _, fid = await farmer(client, 1)
    stale = PendingAction(action_type=PendingActionType.BAN_USER, payload={"user_id": str(fid), "reason": "r" * 12},
                          entity_type="user", entity_id=str(fid), status=PendingActionStatus.APPROVED, decided_at=OLD)
    recent = PendingAction(action_type=PendingActionType.BAN_USER, payload={}, entity_type="user", entity_id="x",
                           status=PendingActionStatus.APPROVED, decided_at=datetime.now(UTC))
    db.add_all([stale, recent])
    await db.commit()
    assert (await svc(redis).fail_interrupted_actions())["failed"] == 1
    a = await fresh(db, PendingAction, stale.id)
    assert a.status == PendingActionStatus.FAILED and a.result == {"error": "interrupted"}
    assert (await fresh(db, PendingAction, recent.id)).status == PendingActionStatus.APPROVED
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "pending_action.failed", AuditLog.entity_id == str(stale.id)))
    assert (await db.scalars(select(Notification).where(Notification.title == "Approved action did not run"))).all()
    assert (await svc(redis).fail_interrupted_actions())["failed"] == 0


# ------------------------------------------------------------------ wrappers, heartbeat, admin endpoint, settings
async def test_run_sweeper_records_outcome_and_never_raises(app_ctx, db, redis):
    out = await run_sweeper({"settings": get_settings(), "redis_client": redis, "queue": RecordingJobQueue()}, "executions")
    assert out["requeued"] == 0
    rec = json.loads(await redis.get("sweeper:last:executions"))
    assert rec["ok"] is True

    class Boom:
        async def enqueue(self, *a, **k):
            pass
    ctx = {"settings": get_settings().model_copy(update={"REDIS_URL": get_settings().REDIS_URL}), "redis_client": redis, "queue": Boom()}
    import app.services.recovery as rec_mod
    orig = rec_mod.RecoveryService.cleanup_expired

    async def fail(self):
        raise RuntimeError("boom")
    rec_mod.RecoveryService.cleanup_expired = fail  # type: ignore[method-assign]
    try:
        assert await run_sweeper(ctx, "cleanup") == {"error": "RuntimeError"}
    finally:
        rec_mod.RecoveryService.cleanup_expired = orig  # type: ignore[method-assign]
    assert json.loads(await redis.get("sweeper:last:cleanup"))["ok"] is False


async def test_admin_workers_endpoint(app_ctx, client, db, redis):
    ah = await make_admin(db, client)
    r = await client.get("/api/v1/admin/workers", headers=ah)
    d = r.json()["data"]
    assert d["alive"] is False and d["heartbeat_age_seconds"] is None and set(d["sweepers"]) == set(SWEEPERS)
    await worker_heartbeat_job({"settings": get_settings(), "redis_client": redis})
    await run_sweeper({"settings": get_settings(), "redis_client": redis, "queue": RecordingJobQueue()}, "analyzing")
    d = (await client.get("/api/v1/admin/workers", headers=ah)).json()["data"]
    assert d["alive"] is True and d["heartbeat_age_seconds"] < 5 and d["sweepers"]["analyzing"]["ok"] is True
    fh, _ = await farmer(client, 1)
    assert (await client.get("/api/v1/admin/workers", headers=fh)).status_code == 403
    assert (await client.get("/api/v1/admin/workers")).status_code in (401, 403)


def test_worker_settings_register_every_job_and_cron():
    names = {f.__name__ for f in WorkerSettings.functions}
    for expected in ("grade_listing_job", "price_listing_job", "match_requirement_job", "assess_risk_job", "expire_reservations_job",
                     "refresh_analytics_job", "embed_market_reports_job", "worker_heartbeat_job"):
        assert expected in names
    assert {f"{k}" for k in ("recover_executions_job", "recover_analyzing_job", "reprocess_webhooks_job", "cleanup_expired_job",
                             "sweep_orphan_images_job", "rematch_requirements_job", "fail_interrupted_actions_job")} <= names
    cron_names = {c.coroutine.__name__ for c in WorkerSettings.cron_jobs}
    assert cron_names <= names and len(WorkerSettings.cron_jobs) >= 10
    assert WorkerSettings.max_tries == 3


async def test_read_worker_status_handles_missing(redis):
    s = await read_worker_status(redis, ["a"])
    assert s == {"heartbeat_age_seconds": None, "alive": False, "sweepers": {"a": None}}
