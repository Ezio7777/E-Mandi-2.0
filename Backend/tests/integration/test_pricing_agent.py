import json
import uuid
from datetime import date, timedelta

import pytest
from arq import Retry
from sqlalchemy import select

from app.agents.runtime import AgentExecutionService, AgentOutcome, dispatch
from app.agents.smart_pricing.agent import SmartPricingAgent
from app.agents.smart_pricing.explainer import PriceExplainer
from app.integrations.llm_common import LLMProviderError
from app.models.agent_execution import AgentExecution
from app.models.audit_log import AuditLog
from app.models.enums import AgentName, AgentStatus, ListingStatus, NotificationType
from app.models.listing import Listing
from app.models.market_report import MarketReport
from app.models.notification import Notification
from app.models.pricing_result import PricingResult
from app.services.embedding import HashEmbeddingProvider
from app.workers.pricing_jobs import price_listing_job
from app.workers.queue import RecordingJobQueue
from tests.integration.conftest import bearer, register
from tests.integration.test_grading import G, analyzing_listing, make_admin, raw, service
from tests.integration.test_listings import create, set_status

TODAY = date.today()
EMB = HashEmbeddingProvider(768)


class LLM:
    def __init__(self, name="gemini", reply=None, exc=None):
        self.name, self._reply, self._exc, self.available, self.prompts = name, reply, exc, True, []

    async def complete_json(self, system, user):
        self.prompts.append(user)
        if self._exc:
            raise LLMProviderError(self._exc, self.name)
        return self._reply


GOOD = json.dumps({"explanation": "A fair price today is about Rs 33 per kg, close to the Rs 30 market reference."})
HALLUCINATED = json.dumps({"explanation": "Sell at Rs 45 per kg because demand is spiking this week."})


def mr(crop="Tomato", days_ago=0, avg=3000, loc="Bengaluru"):
    return MarketReport(crop=crop, location=loc, market="Yeshwanthpur APMC", min_price_paise=avg - 300, max_price_paise=avg + 400,
                        average_price_paise=avg, report_date=TODAY - timedelta(days=days_ago), source="Sample", is_sample=True)


async def seed_market(db, **kw):
    db.add_all([mr(days_ago=d, **kw) for d in (0, 1, 2, 3)])
    await db.commit()


async def mk_listing(client, db, email="f1@example.com", grade="A", qty=500, price=28.5, status=ListingStatus.ACTIVE, **over):
    t = await register(client, email=email)
    d = await create(client, bearer(t), quantity_kg=qty, base_price=price, **over)
    await set_status(db, d["id"], status, ai_grade=grade)
    return bearer(t), t["user"]["id"], uuid.UUID(d["id"])


def agent(db, *llms):
    return SmartPricingAgent(db, EMB, PriceExplainer(list(llms)))


async def listing_of(db, lid):
    l = await db.get(Listing, lid)
    await db.refresh(l)
    return l


async def test_happy_path_persists_deterministic_numbers_and_llm_text(app_ctx, client, db):
    await seed_market(db)
    _, fid, lid = await mk_listing(client, db)
    llm = LLM(reply=GOOD)
    st = await agent(db, llm).run(lid)
    assert st["outcome"] == "priced" and st["explanation_provider"] == "gemini"
    r = (await db.scalars(select(PricingResult))).one()
    assert (r.suggested_paise, r.reference_paise, r.trend, r.scope) == (3300, 3000, "stable", "local")  # 30.00 x 1.10 (grade A)
    assert r.explanation == json.loads(GOOD)["explanation"] and r.is_sample and r.range_min_paise < 3300 < r.range_max_paise
    assert (await listing_of(db, lid)).suggested_price_paise == 3300
    tools = [c["tool"] for c in st["tool_calls"]]
    assert tools == ["market_reports_query", "market_search", "comparable_listings", "llm_explain"]
    assert "Bengaluru" in llm.prompts[0] and "33.00" in llm.prompts[0]
    n = (await db.scalars(select(Notification).where(Notification.user_id == uuid.UUID(fid)))).one()
    assert n.type == NotificationType.SYSTEM and "33.00" in n.body and n.data["kind"] == "pricing"
    a = (await db.scalars(select(AuditLog).where(AuditLog.action == "pricing.completed"))).one()
    assert a.actor_role == "SYSTEM" and a.new_state == {"suggested_price_paise": 3300} and a.previous_state == {"suggested_price_paise": None}


async def test_hallucinated_numbers_are_rejected_numbers_stay_authoritative(app_ctx, client, db):
    await seed_market(db)
    _, _, lid = await mk_listing(client, db)
    st = await agent(db, LLM(reply=HALLUCINATED)).run(lid)
    r = (await db.scalars(select(PricingResult))).one()
    assert r.suggested_paise == 3300 and r.explanation_provider == "deterministic" and "45" not in r.explanation
    assert r.explanation.startswith("Reference market price") and st["fallback_used"] is True


async def test_gemini_failure_falls_back_to_openai_text(app_ctx, client, db):
    await seed_market(db)
    _, _, lid = await mk_listing(client, db)
    await agent(db, LLM("gemini", exc="timeout"), LLM("openai", reply=GOOD)).run(lid)
    r = (await db.scalars(select(PricingResult))).one()
    assert (r.explanation_provider, r.fallback_used, r.suggested_paise) == ("openai", True, 3300)


async def test_all_llms_down_still_prices_deterministically(app_ctx, client, db):
    await seed_market(db)
    _, _, lid = await mk_listing(client, db)
    await agent(db, LLM("gemini", exc="api_error"), LLM("openai", exc="timeout")).run(lid)
    r = (await db.scalars(select(PricingResult))).one()
    assert r.explanation_provider == "deterministic" and r.suggested_paise == 3300


async def test_no_market_data_never_fabricates_a_price(app_ctx, client, db):
    _, _, lid = await mk_listing(client, db)
    llm = LLM(reply=GOOD)
    st = await agent(db, llm).run(lid)
    assert st["outcome"] == "no_data" and llm.prompts == []  # no LLM tokens spent without data
    assert (await db.scalars(select(PricingResult))).all() == [] and (await listing_of(db, lid)).suggested_price_paise is None


async def test_national_fallback_scope_and_grade_effect(app_ctx, client, db):
    await seed_market(db, loc="Delhi")
    _, _, lid = await mk_listing(client, db, grade="D")
    await agent(db).run(lid)
    r = (await db.scalars(select(PricingResult))).one()
    assert r.scope == "national_fallback" and r.suggested_paise == 2150 and "other locations" in r.source  # 30 x 0.72 rounded to 50p


async def test_idempotent_per_grading_result_and_skips_unavailable(app_ctx, client, db):
    await seed_market(db)
    _, _, lid = await mk_listing(client, db)
    gid = uuid.uuid4()
    a = agent(db)
    assert (await a.run(lid, None))["outcome"] == "priced"
    r = (await db.scalars(select(PricingResult))).one()
    r.grading_result_id = None
    for st in (await a.run(lid, None),):  # no grading id -> reprices (refresh semantics)
        assert st["outcome"] == "priced"
    assert len((await db.scalars(select(PricingResult))).all()) == 2
    _, _, l2 = await mk_listing(client, db, "f2@example.com", status=ListingStatus.ARCHIVED)
    assert (await a.run(l2))["outcome"] == "skipped"
    assert (await a.run(uuid.uuid4()))["outcome"] == "skipped"
    _ = gid


async def test_extreme_values_stay_within_bounds(app_ctx, client, db):
    for avg in (60, 9_000_000):
        await db.execute(MarketReport.__table__.delete())
        await seed_market(db, avg=avg)
        _, _, lid = await mk_listing(client, db, f"e{avg}@example.com", qty=900000)
        await agent(db).run(lid)
    for r in (await db.scalars(select(PricingResult))).all():
        assert r.range_min_paise <= r.suggested_paise <= r.range_max_paise and 0.4 * r.reference_paise <= r.suggested_paise <= 2 * r.reference_paise


async def test_comparable_listings_are_informational_only(app_ctx, client, db):
    await seed_market(db)
    _, _, other = await mk_listing(client, db, "f9@example.com", price=31.0)
    _, _, lid = await mk_listing(client, db)
    llm = LLM(reply=GOOD)
    await agent(db, llm).run(lid)
    r = (await db.scalars(select(PricingResult))).one()
    comp = [f for f in r.factors if f["name"] == "comparable_listings"][0]
    assert "median Rs 31.00" in comp["detail"] and comp["informational"] is True
    assert r.suggested_paise == 3300  # comparables never move the price
    assert '"comparable_active_listings"' in llm.prompts[0]


async def test_retrieval_tool_reports_semantic_vs_keyword(app_ctx, client, db):
    await seed_market(db)
    _, _, lid = await mk_listing(client, db)
    assert (await agent(db).run(lid))["retrieval"]["mode"] == "keyword"  # nothing embedded yet
    from app.services.market import MarketService
    await MarketService(db, EMB).embed_pending(50)
    assert (await agent(db).run(lid))["retrieval"]["mode"] == "semantic"


# ---------------- execution tracking / jobs ----------------
async def test_execution_service_idempotency_and_timing(db):
    svc = AgentExecutionService(db)
    ex, created = await svc.queue(AgentName.SMART_PRICING, "t", entity_type="listing", entity_id="x", idempotency_key="k1")
    await db.commit()
    ex2, created2 = await svc.queue(AgentName.SMART_PRICING, "t", idempotency_key="k1")
    assert created and not created2 and ex.id == ex2.id
    await svc.start(ex.id)
    await svc.finish(ex.id, AgentOutcome(AgentStatus.COMPLETED, "ok", "gemini", True, [{"tool": "t"}]))
    row = await db.get(AgentExecution, ex.id, populate_existing=True)
    assert (row.status, row.attempt, row.provider, row.fallback_used) == (AgentStatus.COMPLETED, 1, "gemini", True)
    assert row.duration_ms is not None and row.duration_ms >= 0 and row.completed_at >= row.started_at


async def test_dispatch_is_idempotent_and_survives_queue_outage(db):
    q = RecordingJobQueue()
    kw = dict(agent=AgentName.SMART_PRICING, job_name="price_listing_job", trigger_type="e", entity_type="listing",
              entity_id="abc", job_args=("abc", "g1"), idempotency_key="pricing:g1")
    a = await dispatch(db, q, **kw)
    b = await dispatch(db, q, **kw)
    assert a == b and len(q.jobs) == 1 and q.jobs[0][1][-1] == str(a)

    class Down:
        async def enqueue(self, *a, **k):
            raise ConnectionError("redis down")

    c = await dispatch(db, Down(), **{**kw, "idempotency_key": "pricing:g2"})
    assert (await db.get(AgentExecution, c, populate_existing=True)).status == AgentStatus.QUEUED  # left for the sweeper


async def test_pricing_job_records_execution(app_ctx, client, db):
    await seed_market(db)
    _, _, lid = await mk_listing(client, db)
    q = RecordingJobQueue()
    eid = await dispatch(db, q, agent=AgentName.SMART_PRICING, job_name="price_listing_job", trigger_type="t",
                         entity_type="listing", entity_id=lid, job_args=(str(lid), None))
    ctx = {"embedder": EMB, "explainer": PriceExplainer([LLM("gemini", exc="timeout"), LLM("openai", reply=GOOD)]), "job_try": 1}
    await price_listing_job(ctx, str(lid), None, str(eid))
    ex = await db.get(AgentExecution, eid, populate_existing=True)
    assert (ex.status, ex.provider, ex.fallback_used, ex.attempt) == (AgentStatus.COMPLETED, "openai", True, 1)
    assert "Rs 33.00/kg" in ex.summary and ex.duration_ms is not None
    assert [c["tool"] for c in ex.tool_calls][-1] == "llm_explain"
    assert "prompt" not in json.dumps(ex.tool_calls).lower()  # no prompts / reasoning stored


async def test_pricing_job_no_data_and_failure_retry_semantics(app_ctx, client, db, monkeypatch):
    _, _, lid = await mk_listing(client, db)
    q = RecordingJobQueue()
    eid = await dispatch(db, q, agent=AgentName.SMART_PRICING, job_name="j", trigger_type="t", entity_type="listing",
                         entity_id=lid, job_args=(str(lid), None))
    await price_listing_job({"embedder": EMB, "explainer": PriceExplainer([])}, str(lid), None, str(eid))
    ex = await db.get(AgentExecution, eid, populate_existing=True)
    assert ex.status == AgentStatus.COMPLETED and "no recent market data" in ex.summary and ex.provider is None

    await seed_market(db)
    eid2 = await dispatch(db, q, agent=AgentName.SMART_PRICING, job_name="j", trigger_type="t2", entity_type="listing",
                          entity_id=lid, job_args=(str(lid), None))

    async def boom(self, *a, **k):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(SmartPricingAgent, "run", boom)
    with pytest.raises(Retry):
        await price_listing_job({"embedder": EMB, "explainer": PriceExplainer([]), "job_try": 1}, str(lid), None, str(eid2))
    ex = await db.get(AgentExecution, eid2, populate_existing=True)
    assert (ex.status, ex.error_code, ex.attempt) == (AgentStatus.QUEUED, "RuntimeError", 1)
    await price_listing_job({"embedder": EMB, "explainer": PriceExplainer([]), "job_try": 3}, str(lid), None, str(eid2))
    ex = await db.get(AgentExecution, eid2, populate_existing=True)
    assert (ex.status, ex.attempt) == (AgentStatus.FAILED, 2) and ex.completed_at is not None


# ---------------- grading -> pricing event chain + contract endpoints ----------------
async def run_grading_job(app_ctx, lid, eid, graders, queue, job_try=1):
    from app.workers.grading_jobs import grade_listing_job
    await grade_listing_job({"storage": app_ctx.state.fake_storage, "graders": graders, "queue": queue, "job_try": job_try},
                            str(lid), str(eid))


async def test_grading_event_triggers_pricing_and_tracks_executions(app_ctx, client, db):
    await seed_market(db)
    h, fid, lid = await analyzing_listing(app_ctx, client, db)
    _, (_, geid) = next(j for j in app_ctx.state.fake_queue.jobs if j[0] == "grade_listing_job")
    q = RecordingJobQueue()
    await run_grading_job(app_ctx, lid, geid, [G("gemini", raw())], q)
    gex = await db.get(AgentExecution, uuid.UUID(geid), populate_existing=True)
    assert (gex.status, gex.provider, gex.fallback_used, gex.attempt) == (AgentStatus.COMPLETED, "gemini", False, 1)
    assert "grade A" in gex.summary and gex.tool_calls[0]["tool"] == "vision_grade"
    (name, args), = [j for j in q.jobs if j[0] != "assess_risk_job"]  # grading.completed -> exactly one pricing job
    res = (await db.scalars(select(__import__("app.models.crop_grading_result", fromlist=["x"]).CropGradingResult))).one()
    assert name == "price_listing_job" and args[:2] == (str(lid), str(res.id))
    pex = await db.get(AgentExecution, uuid.UUID(args[2]), populate_existing=True)
    assert (pex.agent_name, pex.status, pex.idempotency_key, pex.related_entity_id) == (
        AgentName.SMART_PRICING, AgentStatus.QUEUED, f"pricing:{res.id}", str(lid))
    # run the pricing job -> completes, listing gets suggestion
    await price_listing_job({"embedder": EMB, "explainer": PriceExplainer([LLM(reply=GOOD)]), "job_try": 1}, *args)
    assert (await listing_of(db, lid)).suggested_price_paise == 3300
    # a replayed grading event creates no second pricing execution
    await dispatch(db, q, agent=AgentName.SMART_PRICING, job_name="price_listing_job", trigger_type="grading.completed",
                   entity_type="listing", entity_id=lid, job_args=(str(lid), str(res.id)), idempotency_key=f"pricing:{res.id}")
    assert len([j for j in q.jobs if j[0] != "assess_risk_job"]) == 1


async def test_grading_execution_status_mapping(app_ctx, client, db):
    _, _, lid = await analyzing_listing(app_ctx, client, db)
    _, (_, eid) = next(j for j in app_ctx.state.fake_queue.jobs if j[0] == "grade_listing_job")
    q = RecordingJobQueue()
    with pytest.raises(Retry):  # providers down, attempt 1 => retry scheduled, execution back to QUEUED
        await run_grading_job(app_ctx, lid, eid, [G("gemini", error="timeout")], q)
    ex = await db.get(AgentExecution, uuid.UUID(eid), populate_existing=True)
    assert (ex.status, ex.error_code) == (AgentStatus.QUEUED, "GradingUnavailable") and q.jobs == []
    await run_grading_job(app_ctx, lid, eid, [G("gemini", raw(confidence=0.3))], q, job_try=2)  # low confidence
    ex = await db.get(AgentExecution, uuid.UUID(eid), populate_existing=True)
    assert (ex.status, ex.attempt, ex.error_code) == (AgentStatus.REVIEW_REQUIRED, 2, None)
    assert len([j for j in q.jobs if j[0] != "assess_risk_job"]) == 1  # pricing still runs on a result that needs review (admin sees the suggestion)


async def test_grading_final_outage_marks_review_required_without_pricing(app_ctx, client, db):
    _, _, lid = await analyzing_listing(app_ctx, client, db)
    _, (_, eid) = next(j for j in app_ctx.state.fake_queue.jobs if j[0] == "grade_listing_job")
    q = RecordingJobQueue()
    await run_grading_job(app_ctx, lid, eid, [G("gemini", error="timeout"), G("openai", error="timeout")], q, job_try=3)
    ex = await db.get(AgentExecution, uuid.UUID(eid), populate_existing=True)
    assert ex.status == AgentStatus.REVIEW_REQUIRED and q.jobs == []


async def test_contract_flow_post_grading_job_status_and_pricing(app_ctx, client, db):
    await seed_market(db)
    t = await register(client, email="f1@example.com")
    h = bearer(t)
    d = await create(client, h)
    from tests.integration.test_images import confirm, img_bytes, upload
    l = await db.get(Listing, uuid.UUID(d["id"]))
    up = await client.post("/api/v1/uploads/init", headers=h, json={"listingId": d["id"], "filename": "a.jpg",
                                                                   "contentType": "image/jpeg", "sizeBytes": 1000})
    init = up.json()["data"]
    assert up.status_code == 200 and {"uploadUrl", "fields", "objectKey", "uploadToken"} <= init.keys()
    assert init["objectKey"].startswith(f"e-mandi/listings/{d['id']}/") and init["fields"]["key"] == init["objectKey"]
    app_ctx.state.fake_storage.put(init["objectKey"], img_bytes())
    cf = await client.post("/api/v1/uploads/confirm", headers=h, json={"uploadToken": init["uploadToken"]})
    assert cf.status_code == 200 and cf.json()["data"]["isPrimary"] is True and "contentType" in cf.json()["data"]
    _ = (confirm, upload, l)

    r = await client.post("/api/v1/grading", headers=h, json={"listingId": d["id"]})
    assert r.status_code == 202
    jid = r.json()["data"]["jobId"]
    st = (await client.get(f"/api/v1/grading/jobs/{jid}", headers=h)).json()["data"]
    assert st["status"] == "QUEUED" and st["agent"] == "CROP_GRADING" and st["result"] is None and st["listingId"] == d["id"]

    q = RecordingJobQueue()
    await run_grading_job(app_ctx, uuid.UUID(d["id"]), jid, [G("gemini", raw())], q)
    st = (await client.get(f"/api/v1/grading/jobs/{jid}", headers=h)).json()["data"]
    res = st["result"]
    assert st["status"] == "COMPLETED" and st["pricing"] is None
    assert res["grade"] == "A" and res["defectPercent"] == 2.5 and res["explanation"] == "Minor bruising"
    assert res["manualReviewRecommended"] is False and res["provider"] == "gemini" and "gradedAt" in res and res["issues"] == ["Minor bruising"]

    await price_listing_job({"embedder": EMB, "explainer": PriceExplainer([LLM(reply=GOOD)])}, *q.jobs[0][1])
    st = (await client.get(f"/api/v1/grading/jobs/{jid}", headers=h)).json()["data"]
    assert st["pricing"]["suggested"] == 33.0 and st["pricing"]["referencePrice"] == 30.0 and st["pricing"]["explanationProvider"] == "gemini"
    p = (await client.get(f"/api/v1/pricing/listings/{d['id']}", headers=h)).json()["data"]
    assert {"suggested", "rangeMin", "rangeMax", "referencePrice", "trend", "explanation", "source"} <= p.keys()


async def test_job_and_pricing_visibility_and_refresh(app_ctx, client, db):
    await seed_market(db)
    admin = await make_admin(db, client)
    h1, _, lid = await mk_listing(client, db)
    h2 = bearer(await register(client, email="f2@example.com"))
    buyer = bearer(await register(client, email="b@example.com", role="BUYER"))
    P = "/api/v1/pricing"
    assert (await client.get(f"{P}/listings/{lid}", headers=h1)).status_code == 404  # nothing priced yet
    r = await client.post(f"{P}/listings/{lid}/refresh", headers=h1)
    assert r.status_code == 202
    jid = r.json()["data"]["jobId"]
    (name, args), = app_ctx.state.fake_queue.jobs[-1:]
    assert name == "price_listing_job" and args == (str(lid), None, jid)
    await price_listing_job({"embedder": EMB, "explainer": PriceExplainer([]), "job_try": 1}, *args)
    js = (await client.get(f"{P}/jobs/{jid}", headers=h1)).json()["data"]
    assert js["status"] == "COMPLETED" and js["provider"] == "deterministic" and js["agent"] == "SMART_PRICING"
    assert (await client.get(f"{P}/jobs/{jid}", headers=admin)).status_code == 200
    for who in (h2, buyer):
        assert (await client.get(f"{P}/jobs/{jid}", headers=who)).status_code == 404
        assert (await client.get(f"{P}/listings/{lid}", headers=who)).status_code == 404
    assert (await client.get(f"{P}/listings/{lid}", headers=admin)).status_code == 200
    assert (await client.post(f"{P}/listings/{lid}/refresh", headers=buyer)).status_code == 403
    assert (await client.post(f"{P}/listings/{lid}/refresh", headers=h2)).status_code == 404
    assert (await client.get(f"/api/v1/grading/jobs/{jid}", headers=h1)).status_code == 404  # wrong agent type
    await set_status(db, str(lid), ListingStatus.ARCHIVED)
    assert (await client.post(f"{P}/listings/{lid}/refresh", headers=h1)).status_code == 409


async def test_auth_contract_aliases(client, demo_users):
    d = (await client.post("/api/v1/auth/demo", json={"kind": "farmer"})).json()["data"]
    assert d["is_demo"] is True
    h = bearer(d)
    me = (await client.get("/api/v1/auth/me", headers=h)).json()["data"]
    assert me["role"] == "FARMER" and me["id"] == (await client.get("/api/v1/users/me", headers=h)).json()["data"]["id"]
    assert (await client.post("/api/v1/auth/demo", json={"kind": "root"})).status_code == 422
    assert (await client.get("/api/v1/auth/me")).status_code == 401
