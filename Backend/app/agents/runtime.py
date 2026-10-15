"""Shared agent runtime: execution records, idempotent event dispatch, tracked runs with retry semantics.
Agents are EVENT-DRIVEN: nothing runs (or spends tokens) until dispatch() enqueues a job for an event."""
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import transactional
from app.core.logging import get_logger
from app.models.agent_execution import AgentExecution
from app.models.enums import AgentName, AgentStatus
from app.utils.must import must
from app.utils.time import utcnow
from app.workers.queue import JobQueue

log = get_logger(__name__)


@dataclass
class AgentOutcome:
    status: AgentStatus
    summary: str
    provider: str | None = None
    fallback_used: bool = False
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class AgentExecutionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def queue(self, agent: AgentName, trigger_type: str, *, entity_type: str | None = None,
                    entity_id: Any = None, idempotency_key: str | None = None) -> tuple[AgentExecution, bool]:
        """Adds a QUEUED record inside the caller's transaction. With an idempotency_key, a duplicate event returns
        the existing record (created=False) instead of creating another run."""
        values = dict(id=uuid.uuid4(), agent_name=agent, trigger_type=trigger_type, status=AgentStatus.QUEUED,
                      idempotency_key=idempotency_key, related_entity_type=entity_type,
                      related_entity_id=str(entity_id) if entity_id is not None else None,
                      attempt=0, fallback_used=False, tool_calls=[])
        if idempotency_key is None:
            ex = AgentExecution(**values)
            self.session.add(ex)
            await self.session.flush()
            return ex, True
        res = await self.session.execute(pg_insert(AgentExecution).values(**values).on_conflict_do_nothing(
            index_elements=["idempotency_key"]).returning(AgentExecution.id))
        new_id = res.scalar_one_or_none()
        stmt = (select(AgentExecution).where(AgentExecution.id == new_id) if new_id
                else select(AgentExecution).where(AgentExecution.idempotency_key == idempotency_key))
        ex = must(await self.session.scalar(stmt), "Agent execution")
        return ex, new_id is not None  # type: ignore[return-value]

    async def get(self, execution_id: uuid.UUID) -> AgentExecution | None:
        return await self.session.get(AgentExecution, execution_id, populate_existing=True)

    async def start(self, execution_id: uuid.UUID) -> AgentExecution | None:
        async with transactional(self.session):
            ex = await self.get(execution_id)
            if ex is None:
                return None
            ex.status, ex.attempt = AgentStatus.RUNNING, ex.attempt + 1
            ex.started_at = ex.started_at or utcnow()
            ex.error_code = None
        return ex

    async def finish(self, execution_id: uuid.UUID, outcome: AgentOutcome, *, error_code: str | None = None) -> None:
        async with transactional(self.session):
            ex = await self.get(execution_id)
            if ex is None:
                return
            ex.status, ex.summary, ex.error_code = outcome.status, outcome.summary[:1000], error_code
            ex.provider, ex.fallback_used, ex.tool_calls = outcome.provider, outcome.fallback_used, outcome.tool_calls
            if outcome.status != AgentStatus.QUEUED:  # QUEUED here means "retry scheduled"
                ex.completed_at = utcnow()
                ex.duration_ms = int((ex.completed_at - (ex.started_at or ex.completed_at)).total_seconds() * 1000)


async def dispatch(session: AsyncSession, queue: JobQueue, *, agent: AgentName, job_name: str, trigger_type: str,
                   entity_type: str, entity_id: Any, job_args: tuple, idempotency_key: str | None = None) -> uuid.UUID:
    """Event -> execution record (committed) -> job. Job args get the execution id appended.
    If the queue is down the record stays QUEUED for the recovery sweeper (Stage 18)."""
    async with transactional(session):
        ex, created = await AgentExecutionService(session).queue(
            agent, trigger_type, entity_type=entity_type, entity_id=entity_id, idempotency_key=idempotency_key)
    if created:
        try:
            await queue.enqueue(job_name, *job_args, str(ex.id))
        except Exception as exc:
            log.error("agent_enqueue_failed", agent=agent.value, execution_id=str(ex.id), error=str(exc))
    return ex.id


async def run_tracked(session: AsyncSession, execution_id: uuid.UUID | None, fn: Callable[[], Awaitable[AgentOutcome]], *,
                      attempt: int, max_attempts: int) -> AgentOutcome:
    """Runs one agent attempt with execution bookkeeping. On exception: QUEUED (retry) or FAILED (final), then re-raises
    so the job wrapper can schedule the retry."""
    svc = AgentExecutionService(session)
    if execution_id:
        await svc.start(execution_id)
    try:
        outcome = await fn()
    except Exception as exc:
        final = attempt >= max_attempts
        if execution_id:
            await session.rollback()
            await svc.finish(execution_id, AgentOutcome(AgentStatus.FAILED if final else AgentStatus.QUEUED,
                             f"{'failed' if final else 'retry scheduled'}: {type(exc).__name__}"), error_code=type(exc).__name__)
        raise
    if execution_id:
        await svc.finish(execution_id, outcome)
    return outcome
