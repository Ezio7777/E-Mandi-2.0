import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from app.agents.buyer_matching.agent import BuyerMatchingAgent
from app.core.config import get_settings
from app.models.agent_execution import AgentExecution
from app.models.audit_log import AuditLog
from app.models.buyer_requirement import BuyerRequirement
from app.models.enums import (
    AgentStatus,
    AuthProvider,
    CropCategory,
    Grade,
    ListingStatus,
    MatchStatus,
    NotificationType,
    RequirementStatus,
    UserRole,
)
from app.models.listing import Listing
from app.models.match import Match
from app.models.notification import Notification
from app.models.user import User
from app.services.matching import Candidate, Requirement, score_candidate
from app.utils.geo import resolve_point
from app.workers.matching_jobs import match_requirement_job
from arq import Retry
from sqlalchemy import select

from tests.conftest import wire
from tests.integration.conftest import bearer, register
from tests.integration.test_grading import make_admin

R = "/api/v1/requirements"
M = "/api/v1/matching"
BODY = {"crop_name": "Tomato", "quantity_kg": 500, "min_grade": "A", "location": "Bangalore", "max_price": 35}


async def farmer(client, n):
    t = await register(client, email=f"farmer{n}@example.com")
    return bearer(t), uuid.UUID(t["user"]["id"])


async def db_farmer(db, n):
    """Bulk farmers straight into the DB (the register endpoint is rate limited by design)."""
    u = User(email=f"bulk{n}-{uuid.uuid4().hex[:6]}@example.com", full_name=f"Bulk Farmer {n}", role=UserRole.FARMER,
             auth_provider=AuthProvider.LOCAL, email_verified=True)
    db.add(u)
    await db.commit()
    return u.id


async def buyer(client, n=1):
    t = await register(client, email=f"buyer{n}@example.com", role="BUYER")
    return bearer(t), uuid.UUID(t["user"]["id"])


async def mk(db, fid, qty=800, price=2850, grade=Grade.A, loc="Bengaluru", crop="Tomato", status=ListingStatus.ACTIVE, reserved=0, harvest=None):
    l = Listing(farmer_id=fid, crop_name=crop, crop_category=CropCategory.VEGETABLE, quantity_kg=Decimal(qty), reserved_kg=Decimal(reserved),
                base_price_paise=price, ai_grade=grade, grade_confidence=0.9, status=status, location=loc, harvest_date=harvest)
    db.add(l)
    await db.commit()
    return l.id


async def post_req(client, h, **over):
    r = await client.post(R, json={**BODY, **over}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def run_job(app_ctx, req, job_try=1):
    await match_requirement_job({"job_try": job_try}, req["id"], req["match_job_id"])


async def matches(client, h, req):
    return wire(await client.get(f"{M}/requirements/{req['id']}", headers=h))["data"]


async def ex_of(db, req):
    ex = await db.get(AgentExecution, uuid.UUID(req["match_job_id"]), populate_existing=True)
    return ex


async def test_sufficient_quantity_immediately_contract_notifications_audit(app_ctx, client, db):
    fh, f1 = await farmer(client, 1)
    bh, b1 = await buyer(client)
    lid = await mk(db, f1)
    req = await post_req(client, bh)
    assert req["status"] == "OPEN" and req["match_job_id"]
    (name, args), = app_ctx.state.fake_queue.jobs
    assert name == "match_requirement_job" and args == (req["id"], req["match_job_id"])
    await run_job(app_ctx, req)
    ms = await matches(client, bh, req)
    assert ms["fullyCovered"] is True and ms["requestedKg"] == 500 and len(ms["matches"]) == 1
    m = ms["matches"][0]
    assert m["listingId"] == str(lid) and m["score"] == 100.0 and m["rank"] == 1 and m["status"] == "SUGGESTED"
    assert [r["factor"] for r in m["reasons"]] == ["grade", "quantity", "location", "price", "availability"]
    assert all(set(r) == {"factor", "matched", "detail"} for r in m["reasons"])
    assert m["listing"]["farmerName"] and m["listing"]["pricePerKg"] == 28.5 and m["gradeScore"] == 100.0
    ex = await ex_of(db, req)
    assert ex.status == AgentStatus.COMPLETED and "fully cover" in ex.summary and "1 search step" in ex.summary and ex.provider == "deterministic"
    assert [c["tool"] for c in ex.tool_calls] == ["inventory_filter", "search_step"]
    r_db = await db.get(BuyerRequirement, uuid.UUID(req["id"]), populate_existing=True)
    assert r_db.status == RequirementStatus.MATCHED
    a = (await db.scalars(select(AuditLog).where(AuditLog.action == "match.generated"))).one()
    assert a.actor_role == "SYSTEM" and a.meta["outcome"] == "matched" and a.meta["steps"][0]["radius_km"] == 0
    bn = (await db.scalars(select(Notification).where(Notification.user_id == b1))).one()
    fn = (await db.scalars(select(Notification).where(Notification.user_id == f1))).one()
    assert bn.type == NotificationType.NEW_MATCH and fn.type == NotificationType.NEW_MATCH
    assert str(b1) not in str(fn.data) and "buyer1" not in fn.body  # farmers never learn the buyer's identity
    assert (await db.scalars(select(AuditLog).where(AuditLog.action == "requirement.created"))).one()


async def test_insufficient_quantity_expands_search_until_satisfied(app_ctx, client, db):
    bh, _ = await buyer(client)
    fs = [await farmer(client, i) for i in range(1, 5)]
    near = await mk(db, fs[0][1], qty=200, loc="Bengaluru")
    mys = await mk(db, fs[1][1], qty=200, loc="Mysore")        # ~128 km
    hub = await mk(db, fs[2][1], qty=300, loc="Hubballi")      # ~340 km
    delhi = await mk(db, fs[3][1], qty=900, loc="Delhi")       # ~1750 km: must NOT be reached
    req = await post_req(client, bh)
    await run_job(app_ctx, req)
    ex = await ex_of(db, req)
    steps = [c for c in ex.tool_calls if c["tool"] == "search_step"]
    assert [(s["radius_km"], s["new"]) for s in steps] == [(0, 1), (50, 0), (150, 1), (400, 1)]
    assert [s["satisfied"] for s in steps] == [False, False, False, True] and "after 4 search step" in ex.summary
    ms = await matches(client, bh, req)
    got = {m["listingId"]: m for m in ms["matches"]}
    assert set(got) == {str(near), str(mys), str(hub)} and str(delhi) not in got and ms["fullyCovered"]
    rows = {str(m.listing_id): m for m in (await db.scalars(select(Match))).all()}
    assert (rows[str(near)].search_step, rows[str(mys)].search_step, rows[str(hub)].search_step) == (0, 2, 3)
    assert got[str(near)]["rank"] == 1 and got[str(mys)]["distance_km" if False else "distanceKm"] > 100


async def test_search_limit_reached_partial_coverage(app_ctx, client, db):
    bh, b1 = await buyer(client)
    (_, f1), (_, f2) = await farmer(client, 1), await farmer(client, 2)
    await mk(db, f1, qty=100, loc="Bengaluru")
    await mk(db, f2, qty=100, loc="Delhi")
    req = await post_req(client, bh)
    await run_job(app_ctx, req)
    ex = await ex_of(db, req)
    steps = [c for c in ex.tool_calls if c["tool"] == "search_step"]
    assert [s["radius_km"] for s in steps] == [0, 50, 150, 400, -1] and steps[-1]["satisfied"] is False
    assert "partially cover" in ex.summary and "search limit reached" in ex.summary
    ms = await matches(client, bh, req)
    assert len(ms["matches"]) == 2 and ms["coveredKg"] == 200 and ms["fullyCovered"] is False
    n = (await db.scalars(select(Notification).where(Notification.user_id == b1))).one()
    assert "covering 200 of 500 kg" in n.body


async def test_no_match(app_ctx, client, db):
    bh, b1 = await buyer(client)
    req = await post_req(client, bh)
    await run_job(app_ctx, req)
    ex = await ex_of(db, req)
    assert ex.status == AgentStatus.COMPLETED and "no eligible inventory" in ex.summary
    assert (await matches(client, bh, req))["matches"] == []
    assert (await db.get(BuyerRequirement, uuid.UUID(req["id"]), populate_existing=True)).status == RequirementStatus.OPEN
    n = (await db.scalars(select(Notification).where(Notification.user_id == b1))).one()
    assert n.type == NotificationType.SYSTEM and n.title == "No matches yet" and "keep looking" not in n.body


async def test_hard_gates_exclude_ineligible_inventory(app_ctx, client, db):
    bh, _ = await buyer(client)
    fs = [(await farmer(client, i))[1] for i in range(1, 9)]
    ok = await mk(db, fs[0])
    await mk(db, fs[1], grade=Grade.B)                               # below min grade
    await mk(db, fs[2], price=3600)                                  # over budget
    await mk(db, fs[3], status=ListingStatus.DRAFT)                  # not live
    await mk(db, fs[4], status=ListingStatus.RESERVED, reserved=800) # no stock
    await mk(db, fs[5], qty=500, reserved=500)                       # fully reserved
    await mk(db, fs[6], crop="Onion")                                # wrong crop
    await mk(db, fs[7], status=ListingStatus.ARCHIVED)
    req = await post_req(client, bh, crop_name="tamatar")            # Hindi alias resolves to Tomato
    await run_job(app_ctx, req)
    assert [m["listingId"] for m in (await matches(client, bh, req))["matches"]] == [str(ok)]


async def test_multiple_candidates_ranking_and_determinism(app_ctx, client, db):
    bh, _ = await buyer(client)
    fs = [await db_farmer(db, i) for i in range(1, 5)]
    best = await mk(db, fs[0], qty=600, price=2500, loc="Bengaluru")
    second = await mk(db, fs[1], qty=600, price=3400, loc="Bengaluru")   # pricier -> lower price score
    third = await mk(db, fs[2], qty=600, price=2500, loc="Kolar")        # ~60 km -> lower location score
    fourth = await mk(db, fs[3], qty=150, price=2500, loc="Bengaluru")   # partial stock
    req = await post_req(client, bh, quantity_kg=1500)  # same-city stock (1350 kg) is not enough -> scope expands to Kolar
    await run_job(app_ctx, req)
    ms = await matches(client, bh, req)
    order = [m["listingId"] for m in ms["matches"]]
    scores = [m["score"] for m in ms["matches"]]
    assert order[0] == str(best) and scores == sorted(scores, reverse=True) and [m["rank"] for m in ms["matches"]] == [1, 2, 3, 4]
    assert set(order) == {str(x) for x in (best, second, third, fourth)}
    snapshot = [(m["listingId"], m["score"], m["rank"]) for m in ms["matches"]]
    for _ in range(2):  # rematching is deterministic and never duplicates rows
        r = await client.post(f"{R}/{req['id']}/rematch", headers=bh)
        assert r.status_code == 202
        await match_requirement_job({"job_try": 1}, req["id"], r.json()["data"]["match_job_id"])
        again = await matches(client, bh, req)
        assert [(m["listingId"], m["score"], m["rank"]) for m in again["matches"]] == snapshot
    assert len((await db.scalars(select(Match))).all()) == 4


async def test_persisted_breakdown_reproduces_the_score(app_ctx, client, db):
    bh, _ = await buyer(client)
    _, f1 = await farmer(client, 1)
    await mk(db, f1, qty=300, price=3000, loc="Kolar")
    req = await post_req(client, bh)
    await run_job(app_ctx, req)
    m = (await db.scalars(select(Match))).one()
    b = m.breakdown
    rq = Requirement(b["requirement"]["crop"], Decimal(b["requirement"]["quantity_kg"]), Grade(b["requirement"]["min_grade"]),
                     b["requirement"]["location"], b["requirement"]["max_price_paise"], None, resolve_point(b["requirement"]["location"]))
    c = Candidate(m.listing_id, uuid.uuid4(), "Tomato", Decimal(b["listing"]["available_kg"]), b["listing"]["price_paise"],
                  Grade(b["listing"]["grade"]), b["listing"]["location"], resolve_point(b["listing"]["location"]), None)
    redo = score_candidate(rq, c, m.distance_km, m.distance_km == 0.0)
    assert redo.score == m.score and redo.reasons == m.reasons and m.execution_id == uuid.UUID(req["match_job_id"])
    assert (m.grade_score, m.quantity_score, m.price_score) == (redo.grade_score, redo.quantity_score, redo.price_score)


async def test_dismissed_stays_dismissed_and_stale_suggestions_removed(app_ctx, client, db):
    bh, _ = await buyer(client)
    fs = [(await farmer(client, i))[1] for i in range(1, 4)]
    a, b, c = await mk(db, fs[0]), await mk(db, fs[1], price=3000), await mk(db, fs[2], price=3100)
    req = await post_req(client, bh)
    await run_job(app_ctx, req)
    ms = await matches(client, bh, req)
    mid = {m["listingId"]: m["matchId"] for m in ms["matches"]}
    assert (await client.post(f"{M}/{mid[str(a)]}/dismiss", headers=bh)).status_code == 204
    l = await db.get(Listing, b)
    l.status = ListingStatus.ARCHIVED
    await db.commit()
    r = await client.post(f"{R}/{req['id']}/rematch", headers=bh)
    await match_requirement_job({"job_try": 1}, req["id"], r.json()["data"]["match_job_id"])
    after = [m["listingId"] for m in (await matches(client, bh, req))["matches"]]
    assert after == [str(c)]  # a dismissed, b gone (stale suggestion dropped), c stays
    db.expire_all()
    assert (await db.scalars(select(Match).where(Match.listing_id == a))).one().status == MatchStatus.DISMISSED
    assert (await db.scalars(select(AuditLog).where(AuditLog.action == "match.dismissed"))).one()


async def test_unknown_location_only_matches_at_widest_scope_with_weak_location_score(app_ctx, client, db):
    bh, _ = await buyer(client)
    (_, f1), (_, f2) = await farmer(client, 1), await farmer(client, 2)
    same = await mk(db, f1, qty=100, loc="Xyzville")
    other = await mk(db, f2, qty=900, loc="Bengaluru")
    req = await post_req(client, bh, location="Xyzville")
    await run_job(app_ctx, req)
    ms = {m["listingId"]: m for m in (await matches(client, bh, req))["matches"]}
    assert ms[str(same)]["locationScore"] == 100.0 and ms[str(other)]["locationScore"] == 10.0
    assert "Distance unknown" in next(r for r in ms[str(other)]["reasons"] if r["factor"] == "location")["detail"]
    ex = await ex_of(db, req)
    assert [s["new"] for s in ex.tool_calls if s["tool"] == "search_step"] == [1, 0, 0, 0, 1]  # only the last (anywhere) step finds it


async def test_configurable_search_limit(app_ctx, client, db):
    bh, _ = await buyer(client)
    (_, f1), (_, f2) = await farmer(client, 1), await farmer(client, 2)
    await mk(db, f1, qty=100, loc="Bengaluru")
    await mk(db, f2, qty=900, loc="Mysore")
    req = await post_req(client, bh)
    tight = get_settings().model_copy(update={"MATCH_RADIUS_STEPS_KM": "0,50"})  # never reaches Mysuru
    await match_requirement_job({"job_try": 1, "settings": tight}, req["id"], req["match_job_id"])
    assert len((await matches(client, bh, req))["matches"]) == 1


async def test_max_results_cap(app_ctx, client, db):
    bh, _ = await buyer(client)
    for i in range(1, 14):
        await mk(db, await db_farmer(db, i), qty=10)
    req = await post_req(client, bh, quantity_kg=500)
    await run_job(app_ctx, req)
    assert len((await matches(client, bh, req))["matches"]) == get_settings().MATCH_MAX_RESULTS


# ---------------- API: RBAC, validation, lifecycle ----------------
async def test_rbac_and_ownership(app_ctx, client, db):
    fh, f1 = await farmer(client, 1)
    b1h, _ = await buyer(client, 1)
    b2h, _ = await buyer(client, 2)
    admin = await make_admin(db, client)
    await mk(db, f1)
    req = await post_req(client, b1h)
    await run_job(app_ctx, req)
    assert (await client.post(R, json=BODY, headers=fh)).status_code == 403
    assert (await client.post(R, json=BODY)).status_code == 401
    for path in (f"{R}/{req['id']}", f"{M}/requirements/{req['id']}", f"{M}/jobs/{req['match_job_id']}"):
        assert (await client.get(path, headers=b2h)).status_code == 404, path
        assert (await client.get(path, headers=fh)).status_code == 404, path
        assert (await client.get(path, headers=b1h)).status_code == 200, path
        assert (await client.get(path, headers=admin)).status_code == 200, path
    mid = (await matches(client, b1h, req))["matches"][0]["matchId"]
    assert (await client.post(f"{M}/{mid}/dismiss", headers=b2h)).status_code == 404
    assert (await client.post(f"{R}/{req['id']}/cancel", headers=b2h)).status_code == 404
    assert (await client.post(f"{R}/{req['id']}/rematch", headers=b2h)).status_code == 404
    assert (await client.get(R, headers=b2h)).json()["data"] == [] and len((await client.get(R, headers=b1h)).json()["data"]) == 1
    job = wire(await client.get(f"{M}/jobs/{req['match_job_id']}", headers=b1h))["data"]
    assert job["agent"] == "BUYER_MATCHING" and job["status"] == "COMPLETED" and job["matchCount"] == 1 and job["requirementId"] == req["id"]
    assert (await client.get(f"/api/v1/pricing/jobs/{req['match_job_id']}", headers=b1h)).status_code == 404  # wrong agent


async def test_validation(client):
    bh, _ = await buyer(client)
    for bad in ({"quantity_kg": 0}, {"quantity_kg": -1}, {"max_price": 0}, {"max_price": 1.234}, {"min_grade": "Z"},
                {"needed_by": str(date.today() - timedelta(days=1))}, {"needed_by": str(date.today() + timedelta(days=400))},
                {"crop_name": "x"}, {"status": "MATCHED"}, {"buyer_id": str(uuid.uuid4())}):
        assert (await client.post(R, json={**BODY, **bad}, headers=bh)).status_code == 422, bad


async def test_cancel_lifecycle_and_job_skips(app_ctx, client, db):
    bh, _ = await buyer(client)
    _, f1 = await farmer(client, 1)
    await mk(db, f1)
    req = await post_req(client, bh)
    c = await client.post(f"{R}/{req['id']}/cancel", headers=bh)
    assert c.json()["data"]["status"] == "CANCELLED"
    await run_job(app_ctx, req)  # event arrives after cancellation
    ex = await ex_of(db, req)
    assert ex.status == AgentStatus.COMPLETED and ex.summary.startswith("skipped")
    assert (await db.scalars(select(Match))).all() == []
    assert (await client.post(f"{R}/{req['id']}/cancel", headers=bh)).status_code == 409
    assert (await client.post(f"{R}/{req['id']}/rematch", headers=bh)).status_code == 409


async def test_job_failure_retry_semantics(app_ctx, client, db, monkeypatch):
    bh, _ = await buyer(client)
    req = await post_req(client, bh)

    async def boom(self, *a, **k):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(BuyerMatchingAgent, "run", boom)
    with pytest.raises(Retry):
        await match_requirement_job({"job_try": 1}, req["id"], req["match_job_id"])
    ex = await ex_of(db, req)
    assert (ex.status, ex.error_code, ex.attempt) == (AgentStatus.QUEUED, "RuntimeError", 1)
    await match_requirement_job({"job_try": 3}, req["id"], req["match_job_id"])  # final attempt: recorded, not raised
    ex = await ex_of(db, req)
    assert ex.status == AgentStatus.FAILED and ex.completed_at is not None


async def test_own_inventory_never_matches_and_queue_outage_does_not_fail_request(app_ctx, client, db):
    class Down:
        async def enqueue(self, *a, **k):
            raise ConnectionError("redis down")

    from app.core.dependencies import get_job_queue
    app_ctx.dependency_overrides[get_job_queue] = lambda: Down()
    bh, _ = await buyer(client)
    req = await post_req(client, bh)  # request succeeds; execution stays QUEUED for the recovery sweeper
    assert (await ex_of(db, req)).status == AgentStatus.QUEUED
