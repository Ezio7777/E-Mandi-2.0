"""Read-only access to the append-only audit log (a DB trigger rejects UPDATE/DELETE; there is no write path here)."""
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


@dataclass
class AuditFilters:
    actor_id: uuid.UUID | None = None
    action: str | None = None          # exact
    action_prefix: str | None = None   # e.g. "payment." (matched literally, never as a LIKE pattern)
    entity_type: str | None = None
    entity_id: str | None = None
    request_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, log_id: uuid.UUID) -> AuditLog | None:
        return await self.session.get(AuditLog, log_id)

    async def search(self, f: AuditFilters, cursor: tuple[datetime, uuid.UUID] | None, limit: int) -> list[AuditLog]:
        stmt = select(AuditLog)
        if f.actor_id:
            stmt = stmt.where(AuditLog.actor_id == f.actor_id)
        if f.action:
            stmt = stmt.where(AuditLog.action == f.action)
        if f.action_prefix:
            stmt = stmt.where(func.starts_with(AuditLog.action, f.action_prefix))  # literal prefix: no LIKE wildcard injection
        if f.entity_type:
            stmt = stmt.where(AuditLog.entity_type == f.entity_type)
        if f.entity_id:
            stmt = stmt.where(AuditLog.entity_id == f.entity_id)
        if f.request_id:
            stmt = stmt.where(AuditLog.request_id == f.request_id)
        if f.since:
            stmt = stmt.where(AuditLog.timestamp >= f.since)
        if f.until:
            stmt = stmt.where(AuditLog.timestamp < f.until)
        if cursor:
            stmt = stmt.where(tuple_(AuditLog.timestamp, AuditLog.id) < tuple_(cursor[0], cursor[1]))
        return list((await self.session.scalars(stmt.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).limit(limit + 1))).all())

    async def timeline(self, entity_type: str, entity_id: str, limit: int) -> list[AuditLog]:
        stmt = select(AuditLog).where(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
        return list((await self.session.scalars(stmt.order_by(AuditLog.timestamp.asc(), AuditLog.id.asc()).limit(limit + 1))).all())

    async def action_counts(self, since: datetime | None) -> list[tuple[str, int]]:
        stmt = select(AuditLog.action, func.count()).group_by(AuditLog.action).order_by(func.count().desc(), AuditLog.action)
        if since:
            stmt = stmt.where(AuditLog.timestamp >= since)
        return [(a, int(n)) for a, n in (await self.session.execute(stmt)).all()]
