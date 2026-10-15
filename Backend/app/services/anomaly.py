"""Admin review of risk flags. A flag is a prompt for human judgement: the admin can dismiss it (false alarm), mark it
resolved, or escalate it into a pending action that another admin must approve. Every decision is audited."""
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import transactional
from app.core.errors import NotFoundError
from app.models.anomaly_event import AnomalyEvent
from app.models.enums import AnomalySeverity, AnomalyStatus, PendingActionType
from app.models.user import User
from app.repositories.anomaly import AnomalyRepository
from app.schemas.admin import AnomalyOut, AnomalyPage
from app.services.approval import ApprovalService
from app.services.audit import Actor, AuditService, RequestContext
from app.services.transitions import ANOMALY_TRANSITIONS, assert_transition
from app.utils.pagination import decode_cursor, encode_cursor
from app.utils.time import utcnow


class AnomalyService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session, self.settings = session, settings
        self.repo, self.audit = AnomalyRepository(session), AuditService(session)

    async def get(self, anomaly_id: uuid.UUID) -> AnomalyEvent:
        a = await self.repo.get(anomaly_id)
        if a is None:
            raise NotFoundError("Anomaly not found")
        return a

    async def list_anomalies(self, status: AnomalyStatus | None, severity: AnomalySeverity | None, entity_type: str | None,
                   cursor: str | None, limit: int) -> AnomalyPage:
        rows = await self.repo.search(status, severity, entity_type, decode_cursor(cursor) if cursor else None, limit)
        more, rows = len(rows) > limit, rows[:limit]
        return AnomalyPage(items=[AnomalyOut.model_validate(r) for r in rows], open_count=await self.repo.open_count(),
                           next_cursor=encode_cursor(rows[-1].detected_at, rows[-1].id) if more else None)

    async def _review(self, admin: User, anomaly_id: uuid.UUID, target: AnomalyStatus, note: str, action: str, ctx: RequestContext) -> AnomalyEvent:
        async with transactional(self.session):
            a = await self.repo.get(anomaly_id, for_update=True)
            if a is None:
                raise NotFoundError("Anomaly not found")
            prev = a.status
            assert_transition(ANOMALY_TRANSITIONS, a.status, target)
            a.status, a.reviewed_by, a.reviewed_at, a.review_note = target, admin.id, utcnow(), note
            self.audit.record(action=action, entity_type="anomaly", entity_id=a.id, actor=Actor(admin.id, admin.role), ip=ctx.ip,
                              metadata={"rule_id": a.rule_id, "severity": a.severity.value, "note": note},
                              previous_state={"status": prev.value}, new_state={"status": target.value})
        return await self.get(anomaly_id)

    async def dismiss(self, admin: User, anomaly_id: uuid.UUID, note: str, ctx: RequestContext) -> AnomalyEvent:
        return await self._review(admin, anomaly_id, AnomalyStatus.DISMISSED, note, "anomaly.dismissed", ctx)

    async def resolve(self, admin: User, anomaly_id: uuid.UUID, note: str, ctx: RequestContext) -> AnomalyEvent:
        return await self._review(admin, anomaly_id, AnomalyStatus.RESOLVED, note, "anomaly.resolved", ctx)

    async def request_action(self, admin: User, anomaly_id: uuid.UUID, action_type: PendingActionType, payload: dict[str, Any],
                             ctx: RequestContext):
        await self.get(anomaly_id)
        return await ApprovalService(self.session, self.settings).request(admin, action_type, payload, ctx, anomaly_id=anomaly_id)
