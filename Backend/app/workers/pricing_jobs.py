"""arq job: Smart Pricing Agent. Triggered by the grading.completed event (see grading_jobs)."""
import uuid
from typing import Any

from arq import Retry

from app.agents.runtime import AgentOutcome, run_tracked
from app.agents.smart_pricing.agent import SmartPricingAgent
from app.agents.smart_pricing.explainer import PriceExplainer
from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.core.logging import get_logger
from app.integrations.gemini.text import GeminiTextLLM
from app.integrations.openai.text import OpenAITextLLM
from app.models.enums import AgentStatus
from app.services.embedding import build_embedding_provider
from app.utils.money import paise_to_rupees

log = get_logger(__name__)
MAX_ATTEMPTS = 3


async def price_listing_job(ctx: dict[str, Any], listing_id: str, grading_result_id: str | None = None,
                            execution_id: str | None = None) -> None:
    settings = get_settings()
    embedder = ctx.get("embedder") or build_embedding_provider(settings)
    explainer = ctx.get("explainer") or PriceExplainer([GeminiTextLLM(settings), OpenAITextLLM(settings)])
    attempt = int(ctx.get("job_try", 1))
    async with get_sessionmaker()() as session:
        agent = SmartPricingAgent(session, embedder, explainer)

        async def fn() -> AgentOutcome:
            st = await agent.run(uuid.UUID(listing_id), uuid.UUID(grading_result_id) if grading_result_id else None)
            calls = st.get("tool_calls", [])
            if st.get("outcome") == "priced":
                rec = st["rec"]
                return AgentOutcome(AgentStatus.COMPLETED,
                                    f"suggested Rs {paise_to_rupees(rec.suggested_paise)}/kg ({rec.scope}, trend {rec.trend})",
                                    st["explanation_provider"], st["fallback_used"], calls)
            if st.get("outcome") == "no_data":
                return AgentOutcome(AgentStatus.COMPLETED, "no recent market data; no suggestion produced", None, False, calls)
            return AgentOutcome(AgentStatus.COMPLETED, "skipped (listing unavailable or already priced)", None, False, calls)

        try:
            await run_tracked(session, uuid.UUID(execution_id) if execution_id else None, fn,
                              attempt=attempt, max_attempts=MAX_ATTEMPTS)
        except Exception as exc:
            if attempt < MAX_ATTEMPTS:
                raise Retry(defer=attempt * 30) from exc
            log.error("pricing_failed_final", listing_id=listing_id, error_type=type(exc).__name__)
