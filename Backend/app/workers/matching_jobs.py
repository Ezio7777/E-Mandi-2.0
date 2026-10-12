"""arq job: Buyer Matching Agent. Triggered by requirement.created / rematch requests."""
import uuid
from typing import Any

from arq import Retry

from app.agents.buyer_matching.agent import BuyerMatchingAgent
from app.agents.runtime import AgentOutcome, run_tracked
from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.core.logging import get_logger
from app.models.enums import AgentStatus

log = get_logger(__name__)
MAX_ATTEMPTS = 3


async def match_requirement_job(ctx: dict[str, Any], requirement_id: str, execution_id: str | None = None) -> None:
    settings = ctx.get("settings") or get_settings()
    attempt = int(ctx.get("job_try", 1))
    async with get_sessionmaker()() as session:
        agent = BuyerMatchingAgent(session, settings)

        async def fn() -> AgentOutcome:
            st = await agent.run(uuid.UUID(requirement_id), uuid.UUID(execution_id) if execution_id else None)
            calls, out = st.get("tool_calls", []), st.get("outcome")
            if out == "skipped":
                return AgentOutcome(AgentStatus.COMPLETED, "skipped (requirement cancelled, fulfilled or missing)", "deterministic", False, calls)
            sel = st.get("selected", [])
            steps = len(st.get("trace", []))
            summary = {"matched": f"{len(sel)} match(es) fully cover the requirement after {steps} search step(s)",
                       "partial": f"{len(sel)} match(es) partially cover the requirement; search limit reached after {steps} step(s)",
                       "no_match": f"no eligible inventory found after {steps} search step(s)"}[out]
            return AgentOutcome(AgentStatus.COMPLETED, summary, "deterministic", False, calls)

        try:
            await run_tracked(session, uuid.UUID(execution_id) if execution_id else None, fn,
                              attempt=attempt, max_attempts=MAX_ATTEMPTS)
        except Exception as exc:
            if attempt < MAX_ATTEMPTS:
                raise Retry(defer=attempt * 30) from exc
            log.error("matching_failed_final", requirement_id=requirement_id, error_type=type(exc).__name__)
