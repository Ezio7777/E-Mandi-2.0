"""Stage 19: concurrency across the new Stage 16-18 surfaces (approvals, sweepers, webhook vs sweeper)."""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.models.agent_execution import AgentExecution
from app.models.enums import AgentName, OrderStatus, PaymentStatus, PendingActionStatus
from app.models.order import Order
from app.models.payment import Payment
from app.models.payment_event import PaymentEvent
from app.models.pending_action import PendingAction
from app.models.user import User
from app.services.payment import PaymentService
from app.workers.queue import RecordingJobQueue
from sqlalchemy import func, select, update

from tests.integration.test_matching_agent import farmer, mk
from tests.integration.test_payments import captured, start
from tests.integration.test_recovery import mk_exec, svc
from tests.integration.test_risk import req, two_admins

A = "/api/v1/admin"
REASON = "Reviewed and agreed by a second admin."


async def test_concurrent_approvals_execute_exactly_once(app_ctx, client, db):
    a1, a2 = await two_admins(db, client)
    from tests.integration.test_grading import make_admin
    a3 = await make_admin(db, client, "admin3@example.com")
    _, fid = await farmer(client, 1)
    d = (await req(client, a1, "BAN_USER", {"user_id": str(fid), "reason": "Repeated abusive listings reported."})).json()["data"]
    res = await asyncio.gather(*[client.post(f"{A}/pending-actions/{d['id']}/approve", json={"reason": REASON}, headers=h)
                                 for h in (a2, a3, a2, a3, a2)])
    codes = sorted(r.status_code for r in res)
    assert codes.count(200) == 1 and all(c == 409 for c in codes if c != 200), codes
    row = await db.get(PendingAction, uuid.UUID(d["id"]), populate_existing=True)
    assert row.status == PendingActionStatus.EXECUTED
    assert (await db.get(User, fid, populate_existing=True)).is_active is False


async def test_concurrent_approve_and_reject_has_one_winner(app_ctx, client, db):
    a1, a2 = await two_admins(db, client)
    from tests.integration.test_grading import make_admin
    a3 = await make_admin(db, client, "admin3@example.com")
    _, fid = await farmer(client, 1)
    d = (await req(client, a1, "BAN_USER", {"user_id": str(fid), "reason": "Repeated abusive listings reported."})).json()["data"]
    res = await asyncio.gather(client.post(f"{A}/pending-actions/{d['id']}/approve", json={"reason": REASON}, headers=a2),
                               client.post(f"{A}/pending-actions/{d['id']}/reject", json={"reason": REASON}, headers=a3))
    assert sorted(r.status_code for r in res) in ([200, 200], [200, 409]) and any(r.status_code == 200 for r in res)
    row = await db.get(PendingAction, uuid.UUID(d["id"]), populate_existing=True)
    banned = not (await db.get(User, fid, populate_existing=True)).is_active
    assert (row.status == PendingActionStatus.EXECUTED) == banned  # never banned without an executed approval


async def test_four_eyes_holds_under_concurrency(app_ctx, client, db):
    a1, a2 = await two_admins(db, client)
    _, fid = await farmer(client, 1)
    d = (await req(client, a1, "BAN_USER", {"user_id": str(fid), "reason": "Repeated abusive listings reported."})).json()["data"]
    res = await asyncio.gather(*[client.post(f"{A}/pending-actions/{d['id']}/approve", json={"reason": REASON}, headers=a1) for _ in range(5)])
    assert all(r.status_code == 403 for r in res)
    assert (await db.get(User, fid, populate_existing=True)).is_active is True


async def test_parallel_sweepers_enqueue_each_execution_once(app_ctx, db, redis):
    for _ in range(5):
        await mk_exec(db, AgentName.BUYER_MATCHING, entity="requirement")
    q = RecordingJobQueue()
    await asyncio.gather(*[svc(redis, q).recover_executions() for _ in range(6)])
    assert len(q.jobs) == 5 and len({a[-1] for _, a in q.jobs}) == 5


async def test_parallel_analyzing_recovery_creates_one_run_per_listing(app_ctx, client, db, redis):
    from app.models.enums import ListingStatus
    from app.models.listing import Listing
    _, fid = await farmer(client, 1)
    lid = await mk(db, fid, status=ListingStatus.ANALYZING)
    await db.execute(update(Listing).where(Listing.id == lid).values(updated_at=datetime.now(UTC) - timedelta(hours=3)))
    await db.commit()
    q = RecordingJobQueue()
    await asyncio.gather(*[svc(redis, q).recover_analyzing() for _ in range(5)])
    n = await db.scalar(select(func.count()).select_from(AgentExecution).where(AgentExecution.related_entity_id == str(lid)))
    assert n >= 1 and len(q.jobs) == n  # every created run was enqueued exactly once, none lost


async def test_live_webhook_and_sweeper_race_applies_once(app_ctx, client, db, redis):
    c = await start(client, db)
    prov = app_ctx.state.fake_provider
    ev = prov.parse_webhook(captured(c), "evt_race_sweep")
    db.add(PaymentEvent(provider="mock", provider_event_id="evt_race_sweep", event_type=ev.type, payload=ev.normalized(),
                        created_at=datetime.now(UTC) - timedelta(hours=1)))
    await db.commit()
    raw = captured(c)

    async def live():
        async with get_sessionmaker()() as s:
            return await PaymentService(s, get_settings(), prov).handle_webhook(raw, prov.sign(raw), "evt_race_sweep")

    sweeps = [svc(redis, provider=prov).reprocess_webhooks() for _ in range(3)]
    await asyncio.gather(live(), live(), *sweeps)
    assert (await db.get(Payment, uuid.UUID(c["pid"]), populate_existing=True)).status == PaymentStatus.SUCCESS
    assert (await db.get(Order, uuid.UUID(c["oid"]), populate_existing=True)).status == OrderStatus.PAID
    rows = (await db.scalars(select(PaymentEvent).where(PaymentEvent.provider_event_id == "evt_race_sweep"))).all()
    assert len(rows) == 1 and rows[0].processed_at is not None


async def test_cleanup_is_safe_to_run_in_parallel(app_ctx, client, db, redis):
    from app.models.idempotency_key import IdempotencyKey
    _, fid = await farmer(client, 1)
    old = datetime.now(UTC) - timedelta(days=2)
    db.add_all([IdempotencyKey(user_id=fid, scope="orders", key=f"k{i}", request_hash="h", expires_at=old) for i in range(30)])
    await db.commit()
    res = await asyncio.gather(*[svc(redis).cleanup_expired() for _ in range(4)])
    assert sum(r["idempotency_keys"] for r in res) == 30
    assert await db.scalar(select(func.count()).select_from(IdempotencyKey)) == 0
