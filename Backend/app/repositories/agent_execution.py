import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_execution import AgentExecution as E
from app.models.enums import AgentName, AgentStatus


class AgentExecutionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, execution_id: uuid.UUID) -> E | None:
        return await self.session.get(E, execution_id, populate_existing=True)

    async def totals_all_time(self) -> dict[AgentName, int]:
        rows = (await self.session.execute(select(E.agent_name, func.count()).group_by(E.agent_name))).all()
        return {a: int(n) for a, n in rows}

    async def window_stats(self, since: datetime, stuck_before: datetime) -> dict[AgentName, dict[str, Any]]:
        def cnt(*statuses: AgentStatus):  # noqa: ANN202
            return func.count().filter(E.status.in_(statuses))

        stmt = (select(E.agent_name, func.count().label("total"), cnt(AgentStatus.COMPLETED).label("ok"),
                       cnt(AgentStatus.FAILED).label("failed"), cnt(AgentStatus.REVIEW_REQUIRED).label("review"),
                       cnt(AgentStatus.QUEUED, AgentStatus.RUNNING).label("inflight"),
                       func.count().filter(E.status.in_([AgentStatus.QUEUED, AgentStatus.RUNNING]), E.created_at < stuck_before).label("stuck"),
                       func.count().filter(E.fallback_used.is_(True)).label("fallback"),
                       func.avg(E.duration_ms).filter(E.duration_ms.is_not(None)).label("avg_ms"))
                .where(E.created_at >= since).group_by(E.agent_name))
        return {r.agent_name: dict(r._mapping) for r in (await self.session.execute(stmt)).all()}

    async def breakdown(self, column: Any, since: datetime) -> dict[AgentName, dict[str, int]]:
        stmt = select(E.agent_name, column, func.count()).where(E.created_at >= since, column.is_not(None)).group_by(E.agent_name, column)
        out: dict[AgentName, dict[str, int]] = {}
        for agent, key, n in (await self.session.execute(stmt)).all():
            out.setdefault(agent, {})[str(key)] = int(n)
        return out

    async def error_codes(self, agent: AgentName, since: datetime, limit: int = 10) -> dict[str, int]:
        stmt = (select(E.error_code, func.count()).where(E.agent_name == agent, E.created_at >= since, E.error_code.is_not(None))
                .group_by(E.error_code).order_by(func.count().desc(), E.error_code).limit(limit))
        return {c: int(n) for c, n in (await self.session.execute(stmt)).all()}

    async def last(self, agent: AgentName) -> E | None:
        return await self.session.scalar(select(E).where(E.agent_name == agent).order_by(E.created_at.desc(), E.id.desc()).limit(1))

    async def search(self, agent: AgentName | None, status: AgentStatus | None, trigger_type: str | None, entity_type: str | None,
                     entity_id: str | None, only_stuck_before: datetime | None, since: datetime | None,
                     cursor: tuple[datetime, uuid.UUID] | None, limit: int) -> list[E]:
        stmt = select(E)
        if agent:
            stmt = stmt.where(E.agent_name == agent)
        if status:
            stmt = stmt.where(E.status == status)
        if trigger_type:
            stmt = stmt.where(E.trigger_type == trigger_type)
        if entity_type:
            stmt = stmt.where(E.related_entity_type == entity_type)
        if entity_id:
            stmt = stmt.where(E.related_entity_id == entity_id)
        if only_stuck_before:
            stmt = stmt.where(E.status.in_([AgentStatus.QUEUED, AgentStatus.RUNNING]), E.created_at < only_stuck_before)
        if since:
            stmt = stmt.where(E.created_at >= since)
        if cursor:
            stmt = stmt.where(tuple_(E.created_at, E.id) < tuple_(cursor[0], cursor[1]))
        return list((await self.session.scalars(stmt.order_by(E.created_at.desc(), E.id.desc()).limit(limit + 1))).all())
