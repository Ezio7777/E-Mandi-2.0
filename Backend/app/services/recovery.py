"""Recovery sweepers: every method is idempotent and safe to run concurrently on several workers.
They only repair *infrastructure* gaps (lost jobs, crashed runs, expired rows); they never make business decisions
(no auto-execution of approvals, no price/inventory changes)."""
import json
import re
import time
import uuid
from datetime import timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import String, cast, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.runtime import AgentExecutionService, AgentOutcome, dispatch
from app.core.config import Settings
from app.core.database import transactional
from app.core.logging import get_logger
from app.integrations.aws.s3 import ObjectStorage
from app.integrations.payments.base import PaymentProvider
from app.models.agent_execution import AgentExecution
from app.models.buyer_requirement import BuyerRequirement
from app.models.enums import (
    AgentName,
    AgentStatus,
    ListingStatus,
    NotificationType,
    PendingActionStatus,
)
from app.models.idempotency_key import IdempotencyKey
from app.models.listing import Listing
from app.models.listing_document import ListingDocument
from app.models.listing_image import ListingImage
from app.models.otp_challenge import OtpChallenge
from app.models.payment_event import PaymentEvent
from app.models.pending_action import PendingAction
from app.models.session import Session
from app.services.audit import SYSTEM_ACTOR, AuditService
from app.services.image import KEY_ROOT
from app.services.notification import NotificationService
from app.services.requirement import ACTIVE_STATES
from app.utils.time import utcnow
from app.workers.queue import JobQueue

log = get_logger(__name__)
IN_FLIGHT = (AgentStatus.QUEUED, AgentStatus.RUNNING)
IMAGE_KEY_RE = re.compile(rf"^{re.escape(KEY_ROOT)}/listings/[0-9a-f-]{{36}}/[^/]+$")
SWEEPER_KEY = "sweeper:last:{}"
HEARTBEAT_KEY = "worker:heartbeat"


def build_payment_provider(settings: Settings) -> PaymentProvider:
    from app.integrations.payments.mock import MockPaymentProvider
    from app.integrations.payments.razorpay import RazorpayProvider
    return RazorpayProvider(settings) if settings.PAYMENT_PROVIDER == "razorpay" else MockPaymentProvider(settings)


class RecoveryService:
    def __init__(self, sm: async_sessionmaker[AsyncSession], settings: Settings, queue: JobQueue, redis: Redis,
                 storage: ObjectStorage | None = None, provider: PaymentProvider | None = None) -> None:
        self.sm, self.settings, self.queue, self.redis = sm, settings, queue, redis
        self.storage, self.provider = storage, provider

    # ------------------------------------------------------------------ helpers
    async def _claim(self, key: str, ttl: int) -> bool:
        """Cooldown: at most one worker acts on `key` per ttl seconds."""
        return bool(await self.redis.set(f"recover:cool:{key}", "1", nx=True, ex=ttl))

    async def _bump(self, key: str) -> int:
        n = await self.redis.incr(f"recover:count:{key}")
        await self.redis.expire(f"recover:count:{key}", 86400)
        return int(n)

    def _job_for(self, ex: AgentExecution) -> tuple[str, tuple] | None:
        eid, xid = ex.related_entity_id, str(ex.id)
        if eid is None:
            return None
        if ex.agent_name == AgentName.CROP_GRADING:
            return "grade_listing_job", (eid, xid)
        if ex.agent_name == AgentName.SMART_PRICING:
            key = ex.idempotency_key or ""
            return "price_listing_job", (eid, key.split(":", 1)[1] if key.startswith("pricing:") else None, xid)
        if ex.agent_name == AgentName.BUYER_MATCHING:
            return "match_requirement_job", (eid, xid)
        if ex.agent_name == AgentName.FRAUD_RISK:
            return "assess_risk_job", (ex.trigger_type, ex.related_entity_type or "", eid, xid)
        return None  # VOICE_ASSISTANT runs inline: nothing to re-run

    # ------------------------------------------------------------------ a) stuck executions
    async def recover_executions(self) -> dict[str, int]:
        now, s = utcnow(), self.settings
        q_cut = now - timedelta(minutes=s.RECOVERY_QUEUED_AFTER_MINUTES)
        r_cut = now - timedelta(minutes=s.RECOVERY_RUNNING_AFTER_MINUTES)
        async with self.sm() as session:
            rows = (await session.scalars(select(AgentExecution).where(
                ((AgentExecution.status == AgentStatus.QUEUED) & (AgentExecution.created_at < q_cut))
                | ((AgentExecution.status == AgentStatus.RUNNING) & (func.coalesce(AgentExecution.started_at, AgentExecution.created_at) < r_cut))
            ).order_by(AgentExecution.created_at).limit(s.RECOVERY_BATCH))).all()
        out = {"requeued": 0, "failed": 0, "skipped": 0}
        for ex in rows:
            job = self._job_for(ex)
            if job is None:
                await self._fail_execution(ex.id, "abandoned", "abandoned: run was lost and cannot be repeated")
                out["failed"] += 1
                continue
            if not await self._claim(f"exec:{ex.id}", s.RECOVERY_QUEUED_AFTER_MINUTES * 60):
                out["skipped"] += 1
                continue
            if await self._bump(f"exec:{ex.id}") > s.RECOVERY_MAX_ATTEMPTS:
                await self._fail_execution(ex.id, "recovery_exhausted", "failed: recovery attempts exhausted")
                if ex.agent_name == AgentName.CROP_GRADING:
                    await self._route_listing_to_review(ex.related_entity_id, "recovery_exhausted")
                out["failed"] += 1
                continue
            async with self.sm() as session, transactional(session):  # back to QUEUED so the job's start() is a clean attempt
                row = await session.get(AgentExecution, ex.id, with_for_update=True, populate_existing=True)
                if row is None or row.status not in IN_FLIGHT:
                    continue
                row.status = AgentStatus.QUEUED
            try:
                await self.queue.enqueue(job[0], *job[1])
                out["requeued"] += 1
            except Exception as exc:
                log.error("recovery_enqueue_failed", execution_id=str(ex.id), error_type=type(exc).__name__)
                out["skipped"] += 1
        return out

    async def _fail_execution(self, execution_id: uuid.UUID, code: str, summary: str) -> None:
        async with self.sm() as session:
            await AgentExecutionService(session).finish(execution_id, AgentOutcome(AgentStatus.FAILED, summary), error_code=code)

    async def _route_listing_to_review(self, listing_id: Any, reason: str) -> None:
        if listing_id is None:
            return
        from app.services.grading import GradingService
        async with self.sm() as session:
            await GradingService(session, self.settings, None, [])._mark_failed(uuid.UUID(str(listing_id)), reason)  # type: ignore[arg-type]

    # ------------------------------------------------------------------ b) listings stuck in ANALYZING
    async def recover_analyzing(self) -> dict[str, int]:
        cut = utcnow() - timedelta(minutes=self.settings.RECOVERY_ANALYZING_AFTER_MINUTES)
        async with self.sm() as session:
            inflight = select(AgentExecution.related_entity_id).where(
                AgentExecution.agent_name == AgentName.CROP_GRADING, AgentExecution.status.in_(IN_FLIGHT),
                AgentExecution.related_entity_type == "listing")
            ids = (await session.scalars(select(Listing.id).where(
                Listing.status == ListingStatus.ANALYZING, Listing.updated_at < cut,
                cast(Listing.id, String).not_in(inflight)).limit(self.settings.RECOVERY_BATCH))).all()
        out = {"requeued": 0, "to_review": 0}
        for lid in ids:
            n = await self._bump(f"analyzing:{lid}")
            if n > self.settings.RECOVERY_MAX_ATTEMPTS:
                await self._route_listing_to_review(lid, "analysis_recovery_exhausted")
                out["to_review"] += 1
                continue
            async with self.sm() as session:
                await dispatch(session, self.queue, agent=AgentName.CROP_GRADING, job_name="grade_listing_job",
                               trigger_type="listing.analysis_recovery", entity_type="listing", entity_id=lid,
                               job_args=(str(lid),), idempotency_key=f"grading-recovery:{lid}:{n}")
            out["requeued"] += 1
        return out

    # ------------------------------------------------------------------ c) unprocessed payment webhooks
    async def reprocess_webhooks(self) -> dict[str, int]:
        from app.services.payment import PaymentService
        cut = utcnow() - timedelta(seconds=self.settings.RECOVERY_WEBHOOK_AFTER_SECONDS)
        async with self.sm() as session:
            ids = (await session.scalars(select(PaymentEvent.id).where(
                PaymentEvent.processed_at.is_(None), PaymentEvent.created_at < cut)
                .order_by(PaymentEvent.created_at).limit(self.settings.RECOVERY_BATCH))).all()
        provider = self.provider or build_payment_provider(self.settings)
        out = {"applied": 0, "failed": 0}
        for eid in ids:
            try:
                async with self.sm() as session:
                    await PaymentService(session, self.settings, provider).reprocess_event(eid)
                out["applied"] += 1
            except Exception as exc:
                log.error("webhook_reprocess_failed", event_row=str(eid), error_type=type(exc).__name__)
                out["failed"] += 1
        return out

    # ------------------------------------------------------------------ d) expired rows
    async def cleanup_expired(self) -> dict[str, int]:
        now, out = utcnow(), {}
        plans: list[tuple[str, Any, Any]] = [("idempotency_keys", IdempotencyKey, IdempotencyKey.expires_at < now),
                 ("otp_challenges", OtpChallenge, OtpChallenge.expires_at < now - timedelta(days=1)),
                 ("sessions", Session, (Session.expires_at < now - timedelta(days=7))
                  | (Session.revoked_at < now - timedelta(days=7)))]
        for name, model, cond in plans:
            total = 0
            while True:
                async with self.sm() as session, transactional(session):
                    ids = (await session.scalars(select(model.id).where(cond).limit(1000))).all()
                    removed = 0
                    if ids:  # rowcount, not len(ids): a parallel sweeper may already have deleted some of these rows
                        removed = getattr(await session.execute(delete(model).where(model.id.in_(ids))), "rowcount", 0) or 0
                total += removed
                if len(ids) < 1000:
                    break
            out[name] = total
        return out

    # ------------------------------------------------------------------ e) orphan S3 objects
    async def sweep_orphan_images(self) -> dict[str, int]:
        if self.storage is None:
            return {"scanned": 0, "deleted": 0}
        s = self.settings
        cut = utcnow() - timedelta(hours=s.ORPHAN_S3_AFTER_HOURS)
        listed = await self.storage.list_keys(f"{KEY_ROOT}/listings/", s.ORPHAN_S3_MAX_DELETES * 5)
        old = [k for k, mod in listed if mod < cut and IMAGE_KEY_RE.match(k)]
        if not old:
            return {"scanned": len(listed), "deleted": 0}
        async with self.sm() as session:  # a DB error here raises BEFORE anything is deleted
            known = set((await session.scalars(select(ListingImage.s3_key).where(ListingImage.s3_key.in_(old)))).all())
            known |= set((await session.scalars(select(ListingDocument.s3_key).where(ListingDocument.s3_key.in_(old)))).all())
        deleted = 0
        for key in old:
            if key in known or deleted >= s.ORPHAN_S3_MAX_DELETES:
                continue
            await self.storage.delete(key)
            deleted += 1
        return {"scanned": len(listed), "deleted": deleted}

    # ------------------------------------------------------------------ f) re-matching on newer listings
    async def rematch_requirements(self) -> dict[str, int]:
        s = self.settings
        since = utcnow() - timedelta(days=s.RECOVERY_REMATCH_DAYS)
        async with self.sm() as session:
            reqs = (await session.scalars(select(BuyerRequirement).where(
                BuyerRequirement.status.in_(ACTIVE_STATES), BuyerRequirement.created_at >= since).limit(s.RECOVERY_BATCH))).all()
        n = 0
        for r in reqs:
            async with self.sm() as session:
                last = await session.scalar(select(func.max(AgentExecution.created_at)).where(
                    AgentExecution.agent_name == AgentName.BUYER_MATCHING, AgentExecution.related_entity_id == str(r.id)))
                busy = await session.scalar(select(func.count()).select_from(AgentExecution).where(
                    AgentExecution.agent_name == AgentName.BUYER_MATCHING, AgentExecution.related_entity_id == str(r.id),
                    AgentExecution.status.in_(IN_FLIGHT)))
                newest = await session.scalar(select(func.max(Listing.updated_at)).where(
                    Listing.status == ListingStatus.ACTIVE, func.lower(Listing.crop_name) == r.crop_name.lower(),
                    Listing.updated_at > (last or r.created_at)))
                if busy or newest is None:
                    continue
                await dispatch(session, self.queue, agent=AgentName.BUYER_MATCHING, job_name="match_requirement_job",
                               trigger_type="requirement.rematch", entity_type="requirement", entity_id=r.id,
                               job_args=(str(r.id),), idempotency_key=f"rematch:{r.id}:{newest.isoformat()}")
                n += 1
        return {"rematched": n}

    # ------------------------------------------------------------------ g) approved-but-never-executed actions
    async def fail_interrupted_actions(self) -> dict[str, int]:
        cut = utcnow() - timedelta(minutes=self.settings.RECOVERY_APPROVED_ACTION_MINUTES)
        async with self.sm() as session:
            ids = (await session.scalars(select(PendingAction.id).where(
                PendingAction.status == PendingActionStatus.APPROVED, PendingAction.decided_at < cut).limit(50))).all()
        done = 0
        for aid in ids:
            async with self.sm() as session, transactional(session):
                row = await session.get(PendingAction, aid, with_for_update=True, populate_existing=True)
                if row is None or row.status != PendingActionStatus.APPROVED:
                    continue
                row.status, row.result = PendingActionStatus.FAILED, {"error": "interrupted"}
                AuditService(session).record(action="pending_action.failed", entity_type="pending_action", entity_id=row.id,
                                             actor=SYSTEM_ACTOR, metadata={"action_type": row.action_type.value, "result": row.result},
                                             previous_state={"status": "APPROVED"}, new_state={"status": "FAILED"})
                await NotificationService(session).notify_admins(
                    NotificationType.SYSTEM, "Approved action did not run",
                    f"An approved {row.action_type.value.replace('_', ' ').lower()} request was interrupted. Please review and re-request it.",
                    {"pending_action_id": str(row.id)})
            done += 1
        return {"failed": done}

    # ------------------------------------------------------------------ bookkeeping for /admin/workers
    async def record(self, name: str, result: dict[str, Any] | None, error: str | None = None) -> None:
        payload = {"at": utcnow().isoformat(), "ok": error is None, "result": result or {}, "error": error}
        await self.redis.set(SWEEPER_KEY.format(name), json.dumps(payload), ex=7 * 86400)


async def read_worker_status(redis: Redis, sweepers: list[str]) -> dict[str, Any]:
    hb = await redis.get(HEARTBEAT_KEY)
    age = None
    if hb:
        age = max(0, int(time.time() - float(hb)))
    last = {}
    for n in sweepers:
        raw = await redis.get(SWEEPER_KEY.format(n))
        last[n] = json.loads(raw) if raw else None
    return {"heartbeat_age_seconds": age, "alive": age is not None and age < 180, "sweepers": last}
