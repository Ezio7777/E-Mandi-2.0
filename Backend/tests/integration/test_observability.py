import uuid
from datetime import timedelta

import pytest
from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.models.agent_execution import AgentExecution
from app.models.audit_log import AuditLog
from app.models.enums import AgentName as AN
from app.models.enums import AgentStatus as AS
from app.models.enums import ListingStatus
from app.utils.time import utcnow
from app.workers.analytics_jobs import refresh_analytics_job
from sqlalchemy import select, text

from tests.integration.conftest import bearer
from tests.integration.test_disputes import dispute, paid
from tests.integration.test_grading import make_admin
from tests.integration.test_matching_agent import farmer, mk
from tests.integration.test_payments import MP, deliver, setup, start
from tests.integration.test_pricing_agent import seed_market
from tests.integration.test_risk import run

AU, AD, AN_ = "/api/v1/audit", "/api/v1/admin", "/api/v1/analytics"


async def ex(db, agent, status, *, trigger="t.event", provider=None, fallback=False, ms=None, err=None, age_min=0, summary="s",
             entity=("listing", "e1")):
    created = utcnow() - timedelta(minutes=age_min)
    row = AgentExecution(agent_name=agent, trigger_type=trigger, status=status, provider=provider, fallback_used=fallback, duration_ms=ms,
                         error_code=err, summary=summary, tool_calls=[{"tool": "x", "ok": True}], attempt=1, related_entity_type=entity[0],
                         related_entity_id=entity[1], created_at=created, started_at=created,
                         completed_at=created if status in (AS.COMPLETED, AS.FAILED, AS.REVIEW_REQUIRED) else None)
    db.add(row)
    await db.commit()
    return row.id


# ================================================================ audit
async def test_audit_is_admin_only_and_read_only(app_ctx, client, db, demo_users):
    admin = await make_admin(db, client)
    fh, _ = await farmer(client, 1)
    for url in (f"{AU}/logs", f"{AU}/actions", f"{AU}/entities/listing/x"):
        assert (await client.get(url)).status_code == 401
        assert (await client.get(url, headers=fh)).status_code == 403
        assert (await client.get(url, headers=admin)).status_code == 200
    demo = bearer((await client.post("/api/v1/auth/demo", json={"kind": "admin"})).json()["data"])
    assert (await client.get(f"{AU}/logs", headers=demo)).status_code == 200
    for method in ("post", "patch", "put", "delete"):
        assert (await getattr(client, method)(f"{AU}/logs", headers=admin)).status_code in (404, 405)
    async with get_sessionmaker()() as s:  # the DB itself refuses tampering (append-only trigger)
        row = (await s.scalars(select(AuditLog).limit(1))).first()
        assert row is not None
        with pytest.raises(Exception, match=r"(?i)append|immutable|not allowed|audit"):
            await s.execute(text("UPDATE audit_logs SET action='x' WHERE id=:i"), {"i": row.id})
            await s.commit()


async def test_audit_filters_pagination_and_literal_prefix(app_ctx, client, db):
    admin = await make_admin(db, client)
    c = await paid(client, app_ctx, db)
    all_ = (await client.get(f"{AU}/logs?limit=100", headers=admin)).json()["data"]["items"]
    assert len(all_) >= 6 and all(k in all_[0] for k in ("id", "actor_id", "action", "entity_type", "entity_id", "timestamp", "metadata",
                                                         "previous_state", "new_state", "ip_address", "request_id"))
    assert [a["timestamp"] for a in all_] == sorted((a["timestamp"] for a in all_), reverse=True)  # newest first
    pay = (await client.get(f"{AU}/logs?action_prefix=payment.&limit=100", headers=admin)).json()["data"]["items"]
    assert pay and all(a["action"].startswith("payment.") for a in pay)
    assert (await client.get(f"{AU}/logs?action_prefix=%25&limit=100", headers=admin)).json()["data"]["items"] == []  # '%' is literal, not a wildcard
    assert (await client.get(f"{AU}/logs?action_prefix=_ayment.", headers=admin)).json()["data"]["items"] == []
    exact = (await client.get(f"{AU}/logs?action=order.created", headers=admin)).json()["data"]["items"]
    assert [a["entity_id"] for a in exact] == [c["oid"]] and exact[0]["actor_id"] == str(c["b1"])
    by_ent = (await client.get(f"{AU}/logs?entity_type=order&entity_id={c['oid']}&limit=100", headers=admin)).json()["data"]["items"]
    assert by_ent and all(a["entity_id"] == c["oid"] for a in by_ent)
    by_actor = (await client.get(f"{AU}/logs?actor_id={c['b1']}&limit=100", headers=admin)).json()["data"]["items"]
    assert by_actor and all(a["actor_id"] == str(c["b1"]) for a in by_actor)
    p1 = (await client.get(f"{AU}/logs?limit=3", headers=admin)).json()["data"]
    p2 = (await client.get(f"{AU}/logs?limit=3&cursor={p1['next_cursor']}", headers=admin)).json()["data"]
    assert len(p1["items"]) == 3 and {a["id"] for a in p1["items"]}.isdisjoint(a["id"] for a in p2["items"])
    now = utcnow()
    future = (now + timedelta(days=1)).isoformat().replace("+", "%2B")
    assert (await client.get(f"{AU}/logs?since={future}", headers=admin)).json()["data"]["items"] == []
    assert (await client.get(f"{AU}/logs?since={future}&until={(now - timedelta(days=1)).isoformat().replace('+', '%2B')}", headers=admin)).status_code == 422
    assert (await client.get(f"{AU}/logs?limit=101", headers=admin)).status_code == 422
    assert (await client.get(f"{AU}/logs?cursor=garbage", headers=admin)).status_code == 422
    one = all_[0]
    assert (await client.get(f"{AU}/logs/{one['id']}", headers=admin)).json()["data"] == one
    assert (await client.get(f"{AU}/logs/{uuid.uuid4()}", headers=admin)).status_code == 404


async def test_entity_timeline_and_action_counts(app_ctx, client, db):
    admin = await make_admin(db, client)
    c = await paid(client, app_ctx, db)
    t = (await client.get(f"{AU}/entities/order/{c['oid']}", headers=admin)).json()["data"]
    acts = [e["action"] for e in t["events"]]
    assert acts[0] == "order.created" and "order.paid" in acts and t["truncated"] is False
    assert [e["timestamp"] for e in t["events"]] == sorted(e["timestamp"] for e in t["events"])  # oldest first
    pay = (await client.get(f"{AU}/entities/payment/{c['pid']}", headers=admin)).json()["data"]
    assert "payment.created" in [e["action"] for e in pay["events"]] and pay["events"][-1]["new_state"]["status"] == "SUCCESS"
    assert (await client.get(f"{AU}/entities/order/{uuid.uuid4()}", headers=admin)).json()["data"]["events"] == []
    counts = {a["action"]: a["count"] for a in (await client.get(f"{AU}/actions", headers=admin)).json()["data"]}
    assert counts["order.created"] == 1 and counts["payment.created"] == 1
    assert (await client.get(f"{AU}/actions?days=1", headers=admin)).status_code == 200
    assert (await client.get(f"{AU}/actions?days=0", headers=admin)).status_code == 422


# ================================================================ agent control center
async def test_control_center_reports_real_numbers_per_agent(app_ctx, client, db):
    admin = await make_admin(db, client)
    G = AN.CROP_GRADING
    for ms in (1000, 2000, 3000):
        await ex(db, G, AS.COMPLETED, trigger="listing.submitted", provider="gemini", ms=ms)
    await ex(db, G, AS.COMPLETED, trigger="listing.submitted", provider="openai", fallback=True, ms=2000)
    await ex(db, G, AS.FAILED, trigger="listing.submitted", err="GradingUnavailable", ms=500)
    await ex(db, G, AS.REVIEW_REQUIRED, trigger="listing.submitted", provider="gemini", ms=1500)
    await ex(db, G, AS.COMPLETED, age_min=60 * 24 * 40, provider="gemini", ms=1)  # outside the 30-day window
    await ex(db, AN.FRAUD_RISK, AS.QUEUED, trigger="listing.created", age_min=30)  # enqueue lost / worker down
    await ex(db, AN.FRAUD_RISK, AS.QUEUED, trigger="listing.created", age_min=1)   # just queued: not stuck
    d = (await client.get(f"{AD}/agents", headers=admin)).json()["data"]
    assert [a["agent"] for a in d["agents"]] == ["CROP_GRADING", "SMART_PRICING", "BUYER_MATCHING", "VOICE_ASSISTANT", "FRAUD_RISK"]
    assert all(a["mode"] == "event_driven" for a in d["agents"]) and d["generated_at"]
    g, sp, vo, fr = (next(a for a in d["agents"] if a["agent"] == n) for n in ("CROP_GRADING", "SMART_PRICING", "VOICE_ASSISTANT", "FRAUD_RISK"))
    assert (g["total_executions"], g["total_executions_all_time"]) == (6, 7)
    assert (g["success_count"], g["failed_count"], g["review_required_count"], g["in_flight_count"]) == (4, 1, 1, 0)
    assert g["success_rate"] == pytest.approx(4 / 6, abs=0.001) and g["avg_duration_ms"] == 1667
    assert (g["fallback_count"], g["fallback_rate"]) == (1, pytest.approx(1 / 6, abs=0.001))
    assert g["providers"] == {"gemini": 4, "openai": 1} and g["triggers"] == {"listing.submitted": 6}
    assert g["last_execution"]["trigger_type"] and g["health"] == "ok" and g["health_reason"] is None
    assert (vo["total_executions"], vo["health"], vo["last_execution"], vo["success_rate"], vo["avg_duration_ms"]) == (0, "idle", None, None, None)
    assert "no executions" in vo["health_reason"] and sp["health"] == "idle"
    assert (fr["in_flight_count"], fr["stuck_count"], fr["health"]) == (2, 1, "attention") and "queued or running" in fr["health_reason"]
    wide = (await client.get(f"{AD}/agents?days=60", headers=admin)).json()["data"]["agents"][0]
    assert wide["total_executions"] == 7 and wide["window_days"] == 60
    assert (await client.get(f"{AD}/agents?days=0", headers=admin)).status_code == 422
    assert (await client.get(f"{AD}/agents?days=366", headers=admin)).status_code == 422


async def test_high_failure_rate_needs_attention_but_small_samples_do_not(app_ctx, client, db):
    admin = await make_admin(db, client)
    for _ in range(5):
        await ex(db, AN.SMART_PRICING, AS.COMPLETED)
    for _ in range(3):
        await ex(db, AN.SMART_PRICING, AS.FAILED, err="Boom")
    await ex(db, AN.BUYER_MATCHING, AS.FAILED, err="Boom")  # 1 of 1 failed, but too little data to judge
    a = {x["agent"]: x for x in (await client.get(f"{AD}/agents", headers=admin)).json()["data"]["agents"]}
    assert a["SMART_PRICING"]["health"] == "attention" and "3 of 8" in a["SMART_PRICING"]["health_reason"]
    assert a["BUYER_MATCHING"]["health"] == "ok"


async def test_agent_detail_and_execution_list(app_ctx, client, db):
    admin = await make_admin(db, client)
    ids = []
    for i in range(4):
        ids.append(await ex(db, AN.SMART_PRICING, AS.COMPLETED, trigger="grading.completed", provider="gemini", ms=100 * (i + 1), age_min=10 - i,
                            entity=("listing", f"L{i}")))
    await ex(db, AN.SMART_PRICING, AS.FAILED, trigger="pricing.refresh_requested", err="NoMarketData", age_min=1, entity=("listing", "L9"))
    await ex(db, AN.SMART_PRICING, AS.FAILED, trigger="pricing.refresh_requested", err="NoMarketData", age_min=2)
    await ex(db, AN.SMART_PRICING, AS.FAILED, trigger="pricing.refresh_requested", err="Timeout", age_min=3)
    d = (await client.get(f"{AD}/agents/SMART_PRICING?recent=3", headers=admin)).json()["data"]
    assert d["summary"]["agent"] == "SMART_PRICING" and d["top_error_codes"] == {"NoMarketData": 2, "Timeout": 1}
    assert len(d["recent"]) == 3 and d["recent"][0]["error_code"] == "NoMarketData"  # newest first
    assert set(d["recent"][0]) == {"id", "agent_name", "trigger_type", "status", "attempt", "provider", "fallback_used", "error_code", "summary",
                                   "tool_calls", "related_entity_type", "related_entity_id", "created_at", "started_at", "completed_at", "duration_ms"}
    assert (await client.get(f"{AD}/agents/NOPE", headers=admin)).status_code == 422
    lst = lambda q: client.get(f"{AD}/agent-executions?{q}", headers=admin)  # noqa: E731
    assert len((await lst("limit=50")).json()["data"]["items"]) == 7
    assert len((await lst("status=FAILED")).json()["data"]["items"]) == 3
    assert len((await lst("trigger_type=grading.completed")).json()["data"]["items"]) == 4
    assert [i["related_entity_id"] for i in (await lst("entity_type=listing&entity_id=L2")).json()["data"]["items"]] == ["L2"]
    assert (await lst("agent=FRAUD_RISK")).json()["data"]["items"] == []
    p1 = (await lst("limit=3")).json()["data"]
    p2 = (await lst(f"limit=3&cursor={p1['next_cursor']}")).json()["data"]
    p3 = (await lst(f"limit=3&cursor={p2['next_cursor']}")).json()["data"]
    assert [len(p["items"]) for p in (p1, p2, p3)] == [3, 3, 1] and p3["next_cursor"] is None
    assert len({i["id"] for p in (p1, p2, p3) for i in p["items"]}) == 7
    one = (await client.get(f"{AD}/agent-executions/{ids[0]}", headers=admin)).json()["data"]
    assert one["id"] == str(ids[0]) and one["duration_ms"] == 100
    assert (await client.get(f"{AD}/agent-executions/{uuid.uuid4()}", headers=admin)).status_code == 404


async def test_stuck_filter_and_access_control(app_ctx, client, db):
    admin = await make_admin(db, client)
    stuck = await ex(db, AN.FRAUD_RISK, AS.RUNNING, age_min=45)
    await ex(db, AN.FRAUD_RISK, AS.QUEUED, age_min=2)
    await ex(db, AN.FRAUD_RISK, AS.COMPLETED, age_min=90)  # old but finished: not stuck
    r = (await client.get(f"{AD}/agent-executions?stuck=true", headers=admin)).json()["data"]["items"]
    assert [i["id"] for i in r] == [str(stuck)]
    fh, _ = await farmer(client, 1)
    for url in (f"{AD}/agents", f"{AD}/agents/FRAUD_RISK", f"{AD}/agent-executions", f"{AD}/agent-executions/{stuck}"):
        assert (await client.get(url)).status_code == 401
        assert (await client.get(url, headers=fh)).status_code == 403


async def test_real_agent_activity_shows_up_in_the_control_center(app_ctx, client, db):
    admin = await make_admin(db, client)
    await seed_market(db)
    _, fid = await farmer(client, 1)
    lid = await mk(db, fid, price=500)
    from app.agents.runtime import dispatch
    from app.workers.queue import RecordingJobQueue
    from app.workers.risk_jobs import assess_risk_job
    eid = await dispatch(db, RecordingJobQueue(), agent=AN.FRAUD_RISK, job_name="assess_risk_job", trigger_type="listing.created",
                         entity_type="listing", entity_id=lid, job_args=("listing.created", "listing", str(lid)))
    await assess_risk_job({"llms": []}, "listing.created", "listing", str(lid), str(eid))
    d = {a["agent"]: a for a in (await client.get(f"{AD}/agents", headers=admin)).json()["data"]["agents"]}["FRAUD_RISK"]
    assert d["total_executions"] == 1 and d["review_required_count"] == 1 and d["providers"] == {"deterministic": 1}
    assert d["last_execution"]["status"] == "REVIEW_REQUIRED" and "flagged for review" in d["last_execution"]["summary"] and d["health"] == "ok"
    assert d["triggers"] == {"listing.created": 1}


# ================================================================ analytics
async def test_analytics_access_control(app_ctx, client, db):
    admin = await make_admin(db, client)
    fh, _ = await farmer(client, 1)
    for url in (f"{AN_}/overview", f"{AN_}/timeseries?metric=orders", f"{AN_}/top-crops"):
        assert (await client.get(url)).status_code == 401
        assert (await client.get(url, headers=fh)).status_code == 403
        assert (await client.get(url, headers=admin)).status_code == 200


async def test_overview_numbers_match_the_data_and_cache_behaves(app_ctx, client, db, redis):
    admin = await make_admin(db, client)
    c = await paid(client, app_ctx, db)  # one PAID order worth Rs 14,250, one successful payment
    c2 = await start(client, db, n=2)
    f = MP.payment_event("failed", provider_order_id=c2["po"], amount_paise=1425000, reason="Declined")
    assert (await deliver(client, app_ctx, f)).json()["status"] == "applied"
    await dispute(client, c)
    r = await client.get(f"{AN_}/overview", headers=admin)
    d, meta = r.json()["data"], r.json()["meta"]
    assert meta == {"cached": False} and d["window_days"] == 30
    assert d["users"]["by_role"] == {"ADMIN": 1, "FARMER": 2, "BUYER": 2} and d["users"]["new_in_window"] == 5 and d["users"]["banned"] == 0
    assert d["listings"]["by_status"] == {"ACTIVE": 2} or d["listings"]["by_status"].get("ACTIVE") == 2
    o = d["orders"]
    assert o["by_status"]["DISPUTED"] == 1 and o["new_in_window"] == 2
    assert o["gmv"] == 14250.0 and o["average_order_value"] == 14250.0  # only the disputed (paid) order counts; the unpaid one does not
    assert d["payments"] == {"succeeded": 1, "failed": 1, "success_rate": 0.5, "refunded": 0.0}
    assert d["risk"]["disputes_open"] == 1 and d["risk"]["pending_approvals"] == 0 and d["risk"]["anomalies_open_by_severity"] == {}
    # cached on the second call; stale until refreshed
    await paid(client, app_ctx, db, n=3)
    again = await client.get(f"{AN_}/overview", headers=admin)
    assert again.json()["meta"] == {"cached": True} and again.json()["data"]["orders"]["gmv"] == 14250.0
    fresh = await client.get(f"{AN_}/overview?refresh=true", headers=admin)
    assert fresh.json()["meta"] == {"cached": False} and fresh.json()["data"]["orders"]["gmv"] == 28500.0
    assert (await client.get(f"{AN_}/overview?days=7", headers=admin)).json()["data"]["window_days"] == 7
    assert (await client.get(f"{AN_}/overview?days=0", headers=admin)).status_code == 422


async def test_empty_marketplace_overview_has_no_division_errors(app_ctx, client, db):
    admin = await make_admin(db, client)
    d = (await client.get(f"{AN_}/overview", headers=admin)).json()["data"]
    assert d["orders"]["gmv"] == 0.0 and d["orders"]["average_order_value"] is None and d["payments"]["success_rate"] is None
    assert d["listings"]["by_status"] == {} and d["users"]["by_role"] == {"ADMIN": 1}


async def test_risk_numbers_in_overview(app_ctx, client, db):
    admin = await make_admin(db, client)
    await seed_market(db)
    _, fid = await farmer(client, 1)
    await run(db, "listing.created", "listing", await mk(db, fid, price=500))
    d = (await client.get(f"{AN_}/overview", headers=admin)).json()["data"]
    assert d["risk"]["anomalies_open_by_severity"] == {"HIGH": 1}


async def test_refresh_job_fills_the_cache(app_ctx, client, db, redis):
    admin = await make_admin(db, client)
    assert await redis.get("analytics:overview:30") is None
    assert await refresh_analytics_job({"redis_client": redis}) == 3
    assert all([await redis.get(f"analytics:overview:{d}") for d in (7, 30, 90)])
    assert (await client.get(f"{AN_}/overview", headers=admin)).json()["meta"] == {"cached": True}


async def test_timeseries_is_zero_filled_and_correct(app_ctx, client, db):
    admin = await make_admin(db, client)
    await paid(client, app_ctx, db)
    ts = (await client.get(f"{AN_}/timeseries?metric=orders&days=7", headers=admin)).json()["data"]
    assert ts["unit"] == "count" and ts["days"] == 7 and len(ts["points"]) == 7 and ts["total"] == 1.0
    days = [p["day"] for p in ts["points"]]
    assert days == sorted(days) and days[-1] == utcnow().date().isoformat() and ts["points"][-1]["value"] == 1.0 and ts["points"][0]["value"] == 0.0
    g = (await client.get(f"{AN_}/timeseries?metric=gmv&days=3", headers=admin)).json()["data"]
    assert g["unit"] == "rupees" and g["total"] == 14250.0 and g["points"][-1]["value"] == 14250.0
    for m, expect in (("signups", 3.0), ("listings", 1.0), ("payments_failed", 0.0), ("disputes", 0.0)):
        assert (await client.get(f"{AN_}/timeseries?metric={m}&days=2", headers=admin)).json()["data"]["total"] == expect, m
    assert (await client.get(f"{AN_}/timeseries?metric=revenue", headers=admin)).status_code == 422
    assert (await client.get(f"{AN_}/timeseries?metric=orders&days=181", headers=admin)).status_code == 422
    assert (await client.get(f"{AN_}/timeseries", headers=admin)).status_code == 422


async def test_top_crops(app_ctx, client, db):
    admin = await make_admin(db, client)
    _, fid = await farmer(client, 1)
    for qty, price in ((100, 2000), (300, 3000)):
        await mk(db, fid, qty=qty, price=price, crop="Tomato")
    await mk(db, fid, qty=50, price=4000, crop="Onion")
    await mk(db, fid, qty=999, price=1, crop="Potato", status=ListingStatus.DRAFT)  # drafts do not count
    d = (await client.get(f"{AN_}/top-crops?limit=5", headers=admin)).json()["data"]
    assert [(i["crop"], i["listings"], i["total_kg"], i["average_price"]) for i in d["items"]] == [("Tomato", 2, 400.0, 25.0), ("Onion", 1, 50.0, 40.0)]
    assert len((await client.get(f"{AN_}/top-crops?limit=1", headers=admin)).json()["data"]["items"]) == 1
    assert (await client.get(f"{AN_}/top-crops?limit=21", headers=admin)).status_code == 422


_ = (get_settings, setup)
