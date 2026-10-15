"""Agent Control Center read model. Everything is derived from agent_executions (safe operational metadata). Agents are
event-driven: this reports what actually ran, never a fake 'running 24/7' status."""
import uuid
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import NotFoundError
from app.models.agent_execution import AgentExecution
from app.models.enums import AgentName, AgentStatus
from app.repositories.agent_execution import AgentExecutionRepository
from app.schemas.agents import AgentDetailOut, AgentSummaryOut, ControlCenterOut, ExecutionOut, ExecutionPage, LastExecution
from app.utils.pagination import decode_cursor, encode_cursor
from app.utils.time import utcnow

DISPLAY = {AgentName.CROP_GRADING: "Crop Grading", AgentName.SMART_PRICING: "Smart Pricing", AgentName.BUYER_MATCHING: "Buyer Matching",
           AgentName.VOICE_ASSISTANT: "Voice Assistant", AgentName.FRAUD_RISK: "Fraud & Risk"}
ORDER = [AgentName.CROP_GRADING, AgentName.SMART_PRICING, AgentName.BUYER_MATCHING, AgentName.VOICE_ASSISTANT, AgentName.FRAUD_RISK]
FAIL_RATE_ATTENTION, FAIL_MIN_SAMPLE = 0.2, 5


def _rate(n: int, d: int) -> float | None:
    return round(n / d, 3) if d else None


class AgentObservabilityService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session, self.settings = session, settings
        self.repo = AgentExecutionRepository(session)

    async def _summaries(self, days: int) -> list[AgentSummaryOut]:
        now = utcnow()
        since, stuck_before = now - timedelta(days=days), now - timedelta(minutes=self.settings.AGENT_STUCK_MINUTES)
        stats, totals = await self.repo.window_stats(since, stuck_before), await self.repo.totals_all_time()
        providers = await self.repo.breakdown(AgentExecution.provider, since)
        triggers = await self.repo.breakdown(AgentExecution.trigger_type, since)
        out: list[AgentSummaryOut] = []
        for a in ORDER:
            s = stats.get(a, {})
            total, ok, failed, review = (int(s.get(k) or 0) for k in ("total", "ok", "failed", "review"))
            stuck, fallback = int(s.get("stuck") or 0), int(s.get("fallback") or 0)
            finished = ok + failed + review
            last = await self.repo.last(a)
            health, reason = "ok", None
            if total == 0:
                health, reason = "idle", f"no executions in the last {days} day(s)"
            elif stuck:
                health, reason = "attention", f"{stuck} execution(s) queued or running for over {self.settings.AGENT_STUCK_MINUTES} minutes"
            elif finished >= FAIL_MIN_SAMPLE and failed / finished >= FAIL_RATE_ATTENTION:
                health, reason = "attention", f"{failed} of {finished} finished executions failed"
            avg = s.get("avg_ms")
            out.append(AgentSummaryOut(
                agent=a, display_name=DISPLAY[a], window_days=days, total_executions=total, total_executions_all_time=totals.get(a, 0),
                success_count=ok, failed_count=failed, review_required_count=review, in_flight_count=int(s.get("inflight") or 0),
                stuck_count=stuck, success_rate=_rate(ok, finished), avg_duration_ms=round(avg) if avg is not None else None,
                fallback_count=fallback, fallback_rate=_rate(fallback, total), providers=providers.get(a, {}), triggers=triggers.get(a, {}),
                last_execution=LastExecution(id=last.id, status=last.status, trigger_type=last.trigger_type, summary=last.summary,
                                             at=last.completed_at or last.started_at or last.created_at) if last else None,
                health=health, health_reason=reason))  # type: ignore[arg-type]
        return out

    async def control_center(self, days: int) -> ControlCenterOut:
        return ControlCenterOut(generated_at=utcnow(), agents=await self._summaries(days))

    async def agent_detail(self, agent: AgentName, days: int, recent: int) -> AgentDetailOut:
        summary = next(s for s in await self._summaries(days) if s.agent == agent)
        rows = (await self.repo.search(agent, None, None, None, None, None, None, None, recent))[:recent]
        return AgentDetailOut(summary=summary, top_error_codes=await self.repo.error_codes(agent, utcnow() - timedelta(days=days)),
                              recent=[ExecutionOut.model_validate(r) for r in rows])

    async def executions(self, agent: AgentName | None, status: AgentStatus | None, trigger_type: str | None, entity_type: str | None,
                         entity_id: str | None, stuck: bool, days: int | None, cursor: str | None, limit: int) -> ExecutionPage:
        now = utcnow()
        rows = await self.repo.search(agent, status, trigger_type, entity_type, entity_id,
                                      now - timedelta(minutes=self.settings.AGENT_STUCK_MINUTES) if stuck else None,
                                      now - timedelta(days=days) if days else None, decode_cursor(cursor) if cursor else None, limit)
        more, rows = len(rows) > limit, rows[:limit]
        return ExecutionPage(items=[ExecutionOut.model_validate(r) for r in rows],
                             next_cursor=encode_cursor(rows[-1].created_at, rows[-1].id) if more else None)

    async def execution(self, execution_id: uuid.UUID) -> ExecutionOut:
        ex = await self.repo.get(execution_id)
        if ex is None:
            raise NotFoundError("Execution not found")
        return ExecutionOut.model_validate(ex)
