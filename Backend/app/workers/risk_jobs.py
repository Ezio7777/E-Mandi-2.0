"""arq job: Fraud & Risk Agent (RiskAssessmentJob). Triggered by business events (listing/order/payment/grading)."""
import uuid
from typing import Any

from arq import Retry

from app.agents.fraud_risk.agent import FraudRiskAgent
from app.agents.runtime import AgentOutcome, run_tracked
from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.core.logging import get_logger
from app.integrations.gemini.text import GeminiTextLLM
from app.integrations.openai.text import OpenAITextLLM
from app.models.enums import AgentStatus

log = get_logger(__name__)
MAX_ATTEMPTS = 3


async def assess_risk_job(ctx: dict[str, Any], event_type: str, entity_type: str, entity_id: str, execution_id: str | None = None) -> None:
    settings = get_settings()
    llms = ctx.get("llms") if ctx.get("llms") is not None else [GeminiTextLLM(settings), OpenAITextLLM(settings)]
    attempt = int(ctx.get("job_try", 1))
    async with get_sessionmaker()() as session:
        agent = FraudRiskAgent(session, settings, llms)

        async def fn() -> AgentOutcome:
            st = await agent.run(event_type, entity_type, entity_id)
            calls, out = st.get("tool_calls", []), st.get("outcome")
            if out == "skipped":
                return AgentOutcome(AgentStatus.COMPLETED, "skipped (entity missing or event not applicable)", "deterministic", False, calls)
            sigs, new = st.get("signals", []), st.get("new_events", [])
            if not sigs:
                return AgentOutcome(AgentStatus.COMPLETED, "no risk signals", "deterministic", False, calls)
            top = max(sigs, key=lambda x: ["LOW", "MEDIUM", "HIGH"].index(x.severity.value)).severity.value
            return AgentOutcome(AgentStatus.REVIEW_REQUIRED,
                                f"{len(sigs)} signal(s) flagged for review ({len(new)} new, highest {top})",
                                st.get("summary_provider") or "deterministic", bool(st.get("degraded")), calls)

        try:
            await run_tracked(session, uuid.UUID(execution_id) if execution_id else None, fn, attempt=attempt, max_attempts=MAX_ATTEMPTS)
        except Exception as exc:
            if attempt < MAX_ATTEMPTS:
                raise Retry(defer=attempt * 30) from exc
            log.error("risk_assessment_failed_final", entity=f"{entity_type}:{entity_id}", error_type=type(exc).__name__)
