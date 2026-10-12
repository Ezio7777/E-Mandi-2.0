"""Human-in-the-loop queue for SENSITIVE actions (ban an account, approve a low-confidence grade, resolve a serious
dispute). Requesters - an admin or the Fraud & Risk Agent - can only CREATE a pending row. Execution happens only after a
DIFFERENT admin approves it (four-eyes; agent requests have no requester so any admin may decide). Every step is audited.
Execution runs as the approving admin through the same services/state machines as the normal admin endpoints, so no new
privileged code path exists. Agents never call execute()."""
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import transactional
from app.core.errors import AppError, ConflictError, DomainValidationError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.models.anomaly_event import AnomalyEvent
from app.models.dispute import Dispute
from app.models.enums import (
    AnomalyStatus, DisputeStatus, ListingStatus, NotificationType, PendingActionStatus, PendingActionType, ReviewDecision, UserRole,
)
from app.models.listing import Listing
from app.models.pending_action import PendingAction
from app.models.user import User
from app.repositories.anomaly import AnomalyRepository
from app.repositories.pending_action import PendingActionRepository
from app.repositories.session import SessionRepository
from app.schemas.admin import PAYLOADS, PendingActionOut, PendingActionPage
from app.schemas.grading import ReviewRequest
from app.services.audit import SYSTEM_ACTOR, Actor, AuditService, RequestContext
from app.services.notification import NotificationService
from app.services.transitions import ANOMALY_TRANSITIONS, assert_transition
from app.utils.pagination import decode_cursor, encode_cursor
from app.utils.time import utcnow

log = get_logger(__name__)
OPEN_DISPUTE = {DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW, DisputeStatus.EVIDENCE_REQUESTED}
ENTITY_KEY = {PendingActionType.BAN_USER: ("user", "user_id"), PendingActionType.APPROVE_LOW_CONFIDENCE_GRADE: ("listing", "listing_id"),
              PendingActionType.RESOLVE_SERIOUS_DISPUTE: ("dispute", "dispute_id")}


def out(r: PendingAction) -> PendingActionOut:
    return PendingActionOut.model_validate(r)


class ApprovalService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session, self.settings = session, settings
        self.repo, self.anomalies = PendingActionRepository(session), AnomalyRepository(session)
        self.audit, self.notify = AuditService(session), NotificationService(session)

    # ------------------------------------------------------------------ reads
    async def get(self, action_id: uuid.UUID) -> PendingAction:
        r = await self.repo.get(action_id)
        if r is None:
            raise NotFoundError("Pending action not found")
        return r

    async def list_actions(self, status: PendingActionStatus | None, action_type: PendingActionType | None, cursor: str | None, limit: int) -> PendingActionPage:
        rows = await self.repo.search(status, action_type, decode_cursor(cursor) if cursor else None, limit)
        more, rows = len(rows) > limit, rows[:limit]
        return PendingActionPage(items=[out(r) for r in rows], pending_count=await self.repo.pending_count(),
                                 next_cursor=encode_cursor(rows[-1].created_at, rows[-1].id) if more else None)

    # ------------------------------------------------------------------ request (creates a row, executes NOTHING)
    async def _validate_target(self, action_type: PendingActionType, p: Any) -> None:
        if action_type == PendingActionType.BAN_USER:
            u = await self.session.get(User, p.user_id)
            if u is None:
                raise NotFoundError("User not found")
            if u.role == UserRole.ADMIN or u.is_demo:
                raise ConflictError("Admin and demo accounts cannot be banned")
            if not u.is_active:
                raise ConflictError("This account is already disabled")
        elif action_type == PendingActionType.APPROVE_LOW_CONFIDENCE_GRADE:
            l = await self.session.get(Listing, p.listing_id)
            if l is None:
                raise NotFoundError("Listing not found")
            if l.status != ListingStatus.REVIEW_REQUIRED:
                raise ConflictError(f"Listing is {l.status.value}; only REVIEW_REQUIRED listings can be approved")
        else:
            d = await self.session.get(Dispute, p.dispute_id)
            if d is None:
                raise NotFoundError("Dispute not found")
            if d.status not in OPEN_DISPUTE:
                raise ConflictError(f"A {d.status.value} dispute cannot be resolved")

    async def request(self, requester: User | None, action_type: PendingActionType, raw_payload: dict[str, Any], ctx: RequestContext,
                      *, via: str = "admin", anomaly_id: uuid.UUID | None = None) -> PendingAction:
        try:
            p = PAYLOADS[action_type].model_validate({**raw_payload, **({"anomaly_id": str(anomaly_id)} if anomaly_id else {})})
        except ValueError as exc:
            raise DomainValidationError("Invalid action payload") from exc
        await self._validate_target(action_type, p)
        etype, key = ENTITY_KEY[action_type]
        eid = str(getattr(p, key))
        if await self.repo.open_for(action_type, etype, eid):
            raise ConflictError("A pending request for this action already exists")
        actor = Actor(requester.id, requester.role) if requester else SYSTEM_ACTOR
        async with transactional(self.session):
            if anomaly_id:
                a = await self.anomalies.get(anomaly_id, for_update=True)
                if a is None:
                    raise NotFoundError("Anomaly not found")
                assert_transition(ANOMALY_TRANSITIONS, a.status, AnomalyStatus.ACTION_REQUESTED)
                a.status = AnomalyStatus.ACTION_REQUESTED
            row = PendingAction(action_type=action_type, payload=p.model_dump(mode="json"), entity_type=etype, entity_id=eid,
                                requested_by=requester.id if requester else None, requested_via=via)
            self.session.add(row)
            await self.session.flush()
            self.audit.record(action="pending_action.requested", entity_type="pending_action", entity_id=row.id, actor=actor, ip=ctx.ip,
                              metadata={"action_type": action_type.value, "target": f"{etype}:{eid}", "via": via},
                              new_state={"status": "PENDING"})
            await self.notify.notify_admins(NotificationType.SYSTEM, "Approval needed",
                                            f"A request to {action_type.value.replace('_', ' ').lower()} is waiting for an admin decision.",
                                            {"pending_action_id": str(row.id)})
        return row

    # ------------------------------------------------------------------ decide
    async def _touch_anomaly(self, row: PendingAction, status: AnomalyStatus) -> None:
        aid = row.payload.get("anomaly_id")
        if not aid:
            return
        a = await self.session.get(AnomalyEvent, uuid.UUID(aid), with_for_update=True, populate_existing=True)
        if a is not None and a.status == AnomalyStatus.ACTION_REQUESTED:
            a.status = status
            if status == AnomalyStatus.RESOLVED:
                a.reviewed_at = utcnow()

    async def approve(self, admin: User, action_id: uuid.UUID, reason: str, ctx: RequestContext) -> PendingAction:
        actor = Actor(admin.id, admin.role)  # captured now: a rollback on the failure path expires the ORM `admin` object
        await self._decide(admin, action_id, True, reason, ctx)
        try:
            result, ok = await self._execute(admin, action_id, ctx), True
        except AppError as exc:
            await self.session.rollback()
            result, ok = {"error": exc.code, "message": exc.message[:300]}, False
        except Exception as exc:  # noqa: BLE001 - never leak internals into the record
            await self.session.rollback()
            log.error("pending_action_execution_failed", action_id=str(action_id), error_type=type(exc).__name__)
            result, ok = {"error": "internal_error"}, False
        async with transactional(self.session):
            row = await self.repo.get(action_id, for_update=True)
            row.status, row.executed_at, row.result = (PendingActionStatus.EXECUTED if ok else PendingActionStatus.FAILED), utcnow(), result
            self.audit.record(action="pending_action.executed" if ok else "pending_action.failed", entity_type="pending_action", entity_id=row.id,
                              actor=actor, ip=ctx.ip, metadata={"action_type": row.action_type.value, "result": result},
                              previous_state={"status": "APPROVED"}, new_state={"status": row.status.value})
            await self._touch_anomaly(row, AnomalyStatus.RESOLVED if ok else AnomalyStatus.FLAGGED_FOR_REVIEW)
        return await self.get(action_id)

    async def reject(self, admin: User, action_id: uuid.UUID, reason: str, ctx: RequestContext) -> PendingAction:
        await self._decide(admin, action_id, False, reason, ctx)
        return await self.get(action_id)

    async def _decide(self, admin: User, action_id: uuid.UUID, approve: bool, reason: str, ctx: RequestContext) -> None:
        async with transactional(self.session):
            row = await self.repo.get(action_id, for_update=True)
            if row is None:
                raise NotFoundError("Pending action not found")
            if row.status != PendingActionStatus.PENDING:
                raise ConflictError(f"This request is already {row.status.value}")
            if row.requested_by == admin.id:
                raise ForbiddenError("A different admin must decide requests you created")
            row.status = PendingActionStatus.APPROVED if approve else PendingActionStatus.REJECTED
            row.decided_by, row.decided_at, row.decision_reason = admin.id, utcnow(), reason
            self.audit.record(action="pending_action.approved" if approve else "pending_action.rejected", entity_type="pending_action",
                              entity_id=row.id, actor=Actor(admin.id, admin.role), ip=ctx.ip,
                              metadata={"action_type": row.action_type.value, "reason": reason, "target": f"{row.entity_type}:{row.entity_id}"},
                              previous_state={"status": "PENDING"}, new_state={"status": row.status.value})
            if not approve:
                await self._touch_anomaly(row, AnomalyStatus.FLAGGED_FOR_REVIEW)

    # ------------------------------------------------------------------ execution (approved rows only)
    async def _execute(self, admin: User, action_id: uuid.UUID, ctx: RequestContext) -> dict[str, Any]:
        row = await self.repo.get(action_id)
        if row is None or row.status != PendingActionStatus.APPROVED:
            raise ConflictError("Only an approved request can be executed")
        p = PAYLOADS[row.action_type].model_validate(row.payload)
        if row.action_type == PendingActionType.BAN_USER:
            return await self._ban(admin, p, ctx)  # type: ignore[arg-type]
        if row.action_type == PendingActionType.APPROVE_LOW_CONFIDENCE_GRADE:
            from app.services.grading import GradingService
            svc = GradingService(self.session, self.settings, None, [])  # type: ignore[arg-type]  # review path needs no storage/graders
            l = await svc.review_listing(admin, p.listing_id, ReviewRequest(decision=ReviewDecision.APPROVED, reason=p.reason), ctx)  # type: ignore[attr-defined]
            return {"listing_id": str(l.id), "status": l.status.value}
        from app.services.dispute import DisputeService
        d = await DisputeService(self.session, self.settings).resolve(admin, p.dispute_id, p.outcome, p.resolution, ctx)  # type: ignore[attr-defined]
        return {"dispute_id": str(d.id), "status": d.status.value}

    async def _ban(self, admin: User, p: Any, ctx: RequestContext) -> dict[str, Any]:
        async with transactional(self.session):
            u = await self.session.scalar(select(User).where(User.id == p.user_id).with_for_update().execution_options(populate_existing=True))
            if u is None:
                raise NotFoundError("User not found")
            if u.role == UserRole.ADMIN or u.is_demo:
                raise ConflictError("Admin and demo accounts cannot be banned")
            if not u.is_active:
                raise ConflictError("This account is already disabled")
            now = utcnow()
            u.is_active, u.banned_at, u.ban_reason = False, now, p.reason
            await SessionRepository(self.session).revoke_all_for_user(u.id, now)  # every refresh token dies with the ban
            self.audit.record(action="user.banned", entity_type="user", entity_id=u.id, actor=Actor(admin.id, admin.role), ip=ctx.ip,
                              metadata={"reason": p.reason}, previous_state={"is_active": True}, new_state={"is_active": False})
        return {"user_id": str(p.user_id), "is_active": False}
