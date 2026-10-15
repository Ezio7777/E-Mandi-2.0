import uuid

import pytest
from app.core.config import get_settings
from app.core.security import hash_password
from app.integrations.vision_common import GradingProviderError
from app.models.agent_execution import AgentExecution
from app.models.audit_log import AuditLog
from app.models.crop_grading_result import CropGradingResult
from app.models.enums import AgentName, AgentStatus, AuthProvider, GradingProvider, ListingStatus, NotificationType, UserRole
from app.models.grading_review import GradingReview
from app.models.listing import Listing
from app.models.notification import Notification
from app.models.user import User
from app.schemas.grading import RawGrading
from app.services.grading import GradingService, GradingUnavailable
from app.workers.grading_jobs import grade_listing_job
from app.workers.queue import RecordingJobQueue
from arq import Retry
from sqlalchemy import select

from tests.integration.conftest import bearer, register
from tests.integration.test_images import confirm, img_bytes, upload
from tests.integration.test_listings import create

S = get_settings()
GOOD = dict(grade="A", confidence=0.94, defect_percentage=2.5, reason="Minor bruising", issues=["Minor bruising"])


class G:
    def __init__(self, name, result=None, error=None):
        self.name, self._r, self._e, self.calls = name, result, error, 0
        self.available = True

    async def grade(self, image, ct, crop):
        self.calls += 1
        if self._e:
            raise GradingProviderError(self._e, self.name)
        return self._r


def raw(**over):
    return RawGrading(**{**GOOD, **over})


async def make_admin(db, client, email="admin@example.com"):
    db.add(User(email=email, full_name="Admin", role=UserRole.ADMIN, password_hash=hash_password("AdminPass123"),
                email_verified=True, auth_provider=AuthProvider.LOCAL))
    await db.commit()
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": "AdminPass123"})
    return bearer(r.json()["data"])


async def analyzing_listing(app_ctx, client, db, email="f1@example.com", image=None, **over):
    t = await register(client, email=email)
    h = bearer(t)
    d = await create(client, h, **over)
    l = await db.get(Listing, uuid.UUID(d["id"]))
    await confirm(client, h, await upload(client, app_ctx, h, l, image or img_bytes()))
    r = await client.post(f"/api/v1/listings/{d['id']}/submit", headers=h)
    assert r.status_code == 200
    return h, t["user"]["id"], uuid.UUID(d["id"])


def service(app_ctx, db, *graders):
    return GradingService(db, S, app_ctx.state.fake_storage, list(graders))


async def refresh(db, lid):
    l = await db.get(Listing, lid)
    await db.refresh(l)
    return l


async def test_submit_enqueues_job_after_commit(app_ctx, client, db):
    _, _, lid = await analyzing_listing(app_ctx, client, db)
    (name, args), = [j for j in app_ctx.state.fake_queue.jobs if j[0] != "assess_risk_job"]  # (risk events are asserted in test_risk.py)
    assert name == "grade_listing_job" and args[0] == str(lid) and len(args) == 2
    ex = await db.get(AgentExecution, uuid.UUID(args[1]))  # the execution id is the frontend jobId
    assert (ex.agent_name, ex.status, ex.related_entity_id) == (AgentName.CROP_GRADING, AgentStatus.QUEUED, str(lid))


async def test_high_confidence_publishes(app_ctx, client, db):
    _, fid, lid = await analyzing_listing(app_ctx, client, db)
    g = G("gemini", raw())
    res = await service(app_ctx, db, g).grade_listing(lid)
    l = await refresh(db, lid)
    assert (l.status, l.ai_grade, l.grade_confidence) == (ListingStatus.ACTIVE, "A", 0.94) or l.status == ListingStatus.ACTIVE
    assert res.provider == GradingProvider.GEMINI and not res.fallback_used and not res.from_cache and not res.requires_review
    n = (await db.scalars(select(Notification).where(Notification.user_id == uuid.UUID(fid)))).all()
    assert [x.type for x in n] == [NotificationType.GRADING_COMPLETED]
    a = (await db.scalars(select(AuditLog).where(AuditLog.action == "grading.completed"))).one()
    assert a.meta["provider"] == "gemini" and a.actor_role == "SYSTEM"


async def test_low_confidence_goes_to_review_and_notifies_admins(app_ctx, client, db):
    await make_admin(db, client)
    _, fid, lid = await analyzing_listing(app_ctx, client, db)
    res = await service(app_ctx, db, G("gemini", raw(confidence=0.5))).grade_listing(lid)
    l = await refresh(db, lid)
    assert l.status == ListingStatus.REVIEW_REQUIRED and res.requires_review
    types = {(n.type, str(n.user_id) == fid) for n in (await db.scalars(select(Notification))).all()}
    assert (NotificationType.REVIEW_REQUIRED, True) in types and (NotificationType.REVIEW_REQUIRED, False) in types
    assert (await db.scalars(select(AuditLog).where(AuditLog.action == "grading.review_required"))).one()


async def test_inconsistent_result_forces_review_even_if_confident(app_ctx, client, db):
    _, _, lid = await analyzing_listing(app_ctx, client, db)
    await service(app_ctx, db, G("gemini", raw(grade="A", defect_percentage=45.0, confidence=0.99))).grade_listing(lid)
    assert (await refresh(db, lid)).status == ListingStatus.REVIEW_REQUIRED


async def test_fallback_persisted(app_ctx, client, db):
    _, _, lid = await analyzing_listing(app_ctx, client, db)
    res = await service(app_ctx, db, G("gemini", error="timeout"), G("openai", raw(grade="B", defect_percentage=8.0))).grade_listing(lid)
    assert (res.provider, res.fallback_used) == (GradingProvider.OPENAI, True)
    assert (await refresh(db, lid)).status == ListingStatus.ACTIVE


async def test_cache_reuse_same_image_and_crop_only(app_ctx, client, db):
    same = img_bytes(size=(420, 310))
    _, _, l1 = await analyzing_listing(app_ctx, client, db, image=same)
    g1 = G("gemini", raw())
    await service(app_ctx, db, g1).grade_listing(l1)
    _, _, l2 = await analyzing_listing(app_ctx, client, db, "f2@example.com", image=same)  # same bytes, same crop
    g2 = G("gemini", raw(grade="D"))
    r2 = await service(app_ctx, db, g2).grade_listing(l2)
    assert g2.calls == 0 and r2.from_cache and r2.grade.value == "A" and r2.provider == GradingProvider.GEMINI
    _, _, l3 = await analyzing_listing(app_ctx, client, db, "f3@example.com", image=same, crop_name="Onion")
    g3 = G("gemini", raw(grade="C", defect_percentage=20.0))
    r3 = await service(app_ctx, db, g3).grade_listing(l3)
    assert g3.calls == 1 and not r3.from_cache  # different crop label => not safe to reuse


async def test_provider_outage_retry_then_manual_review(app_ctx, client, db):
    await make_admin(db, client)
    _, _, lid = await analyzing_listing(app_ctx, client, db)
    bad = lambda: [G("gemini", error="timeout"), G("openai", error="api_error")]  # noqa: E731
    with pytest.raises(GradingUnavailable):
        await service(app_ctx, db, *bad()).grade_listing(lid)
    assert (await refresh(db, lid)).status == ListingStatus.ANALYZING  # stays put so the job can retry
    assert await service(app_ctx, db, *bad()).grade_listing(lid, final_attempt=True) is None
    assert (await refresh(db, lid)).status == ListingStatus.REVIEW_REQUIRED
    assert (await db.scalars(select(AuditLog).where(AuditLog.action == "grading.failed"))).one()
    assert (await db.scalars(select(CropGradingResult))).all() == []  # no fabricated AI result


async def test_grading_is_idempotent(app_ctx, client, db):
    _, _, lid = await analyzing_listing(app_ctx, client, db)
    g = G("gemini", raw())
    await service(app_ctx, db, g).grade_listing(lid)
    assert await service(app_ctx, db, g).grade_listing(lid) is None and g.calls == 1
    assert len((await db.scalars(select(CropGradingResult))).all()) == 1


async def test_worker_job_success_and_retry(app_ctx, client, db):
    _, _, lid = await analyzing_listing(app_ctx, client, db)
    ctx = {"storage": app_ctx.state.fake_storage, "graders": [G("gemini", error="timeout")], "job_try": 1, "queue": RecordingJobQueue()}
    with pytest.raises(Retry):
        await grade_listing_job(ctx, str(lid))
    ctx.update(graders=[G("gemini", raw())], job_try=2)
    await grade_listing_job(ctx, str(lid))
    assert (await refresh(db, lid)).status == ListingStatus.ACTIVE
    _, _, l2 = await analyzing_listing(app_ctx, client, db, "f2@example.com", image=img_bytes(size=(333, 444)))
    await grade_listing_job({**ctx, "graders": [G("gemini", error="timeout")], "job_try": S.GRADING_MAX_ATTEMPTS}, str(l2))
    assert (await refresh(db, l2)).status == ListingStatus.REVIEW_REQUIRED


# ---------------- admin review ----------------
async def to_review(app_ctx, client, db, **kw):
    h, fid, lid = await analyzing_listing(app_ctx, client, db, **kw)
    await service(app_ctx, db, G("gemini", raw(confidence=0.4))).grade_listing(lid)
    return h, fid, lid


R = "/api/v1/grading"


async def test_review_queue_rbac_and_content(app_ctx, client, db):
    admin = await make_admin(db, client)
    fh, _, lid = await to_review(app_ctx, client, db)
    q = (await client.get(f"{R}/reviews", headers=admin)).json()["data"]
    assert len(q) == 1 and q[0]["listing_id"] == str(lid) and q[0]["flags"] == ["low_confidence"]
    assert (await client.get(f"{R}/reviews", headers=fh)).status_code == 403
    assert (await client.get(f"{R}/reviews")).status_code == 401
    body = {"decision": "APPROVED", "reason": "looks fine to me"}
    assert (await client.post(f"{R}/listings/{lid}/review", json=body, headers=fh)).status_code == 403


async def test_admin_approve(app_ctx, client, db):
    admin = await make_admin(db, client)
    fh, fid, lid = await to_review(app_ctx, client, db)
    r = await client.post(f"{R}/listings/{lid}/review", json={"decision": "APPROVED", "reason": "photo is clear"}, headers=admin)
    assert r.status_code == 200 and r.json()["data"]["status"] == "ACTIVE" and r.json()["data"]["ai_grade"] == "A"
    rev = (await db.scalars(select(GradingReview))).one()
    assert rev.original_result["confidence"] == 0.4 and rev.decision.value == "APPROVED" and rev.admin_id
    a = (await db.scalars(select(AuditLog).where(AuditLog.action == "grading.review_approved"))).one()
    assert a.actor_role == "ADMIN" and a.previous_state["status"] == "REVIEW_REQUIRED"
    assert (await client.post(f"{R}/listings/{lid}/review", json={"decision": "APPROVED", "reason": "again again"}, headers=admin)).status_code == 409


async def test_admin_override_and_validation(app_ctx, client, db):
    admin = await make_admin(db, client)
    _, _, lid = await to_review(app_ctx, client, db)
    url = f"{R}/listings/{lid}/review"
    assert (await client.post(url, json={"decision": "OVERRIDDEN", "reason": "graded by hand"}, headers=admin)).status_code == 422
    assert (await client.post(url, json={"decision": "APPROVED", "final_grade": "B", "reason": "graded by hand"}, headers=admin)).status_code == 422
    assert (await client.post(url, json={"decision": "APPROVED", "reason": "x"}, headers=admin)).status_code == 422
    r = await client.post(url, json={"decision": "OVERRIDDEN", "final_grade": "C", "reason": "visible mould on crate"}, headers=admin)
    d = r.json()["data"]
    assert d["status"] == "ACTIVE" and d["ai_grade"] == "C"
    a = (await db.scalars(select(AuditLog).where(AuditLog.action == "grading.overridden"))).one()
    assert a.previous_state["ai"]["grade"] == "A" and a.new_state["grade"] == "C"
    assert (await db.scalars(select(GradingReview))).one().final_grade.value == "C"
    assert GradingProvider.MANUAL in [r.provider for r in (await db.scalars(select(CropGradingResult))).all()]


async def test_admin_reject_and_no_ai_result_cases(app_ctx, client, db):
    admin = await make_admin(db, client)
    _, _, lid = await to_review(app_ctx, client, db)
    r = await client.post(f"{R}/listings/{lid}/review", json={"decision": "REJECTED", "reason": "wrong crop pictured"}, headers=admin)
    assert r.json()["data"]["status"] == "ARCHIVED"
    _, _, l2 = await analyzing_listing(app_ctx, client, db, "f2@example.com", image=img_bytes(size=(350, 350)))
    await service(app_ctx, db, G("gemini", error="timeout"), G("openai", error="timeout")).grade_listing(l2, final_attempt=True)
    q = (await client.get(f"{R}/reviews", headers=admin)).json()["data"]
    assert q[0]["ai_result"] is None and q[0]["flags"] == ["ai_unavailable"]
    assert (await client.post(f"{R}/listings/{l2}/review", json={"decision": "APPROVED", "reason": "cannot approve nothing"}, headers=admin)).status_code == 409
    ok = await client.post(f"{R}/listings/{l2}/review", json={"decision": "OVERRIDDEN", "final_grade": "B", "reason": "checked manually"}, headers=admin)
    assert ok.json()["data"]["status"] == "ACTIVE"


async def test_result_visibility(app_ctx, client, db):
    admin = await make_admin(db, client)
    fh, _, lid = await analyzing_listing(app_ctx, client, db)
    other = bearer(await register(client, email="f2@example.com"))
    assert (await client.get(f"{R}/listings/{lid}", headers=fh)).status_code == 404  # nothing graded yet
    await service(app_ctx, db, G("gemini", raw())).grade_listing(lid)
    r = await client.get(f"{R}/listings/{lid}", headers=fh)
    assert r.status_code == 200 and r.json()["data"]["grade"] == "A"
    assert (await client.get(f"{R}/listings/{lid}", headers=admin)).status_code == 200
    assert (await client.get(f"{R}/listings/{lid}", headers=other)).status_code == 404
