"""arq job: Crop Grading Agent. Idempotent; retried with backoff; final attempt routes to manual review.
Emits the grading.completed event by dispatching the Smart Pricing Agent after a result is persisted."""
import uuid
from typing import Any

from arq import Retry

from app.agents.runtime import AgentOutcome, dispatch, run_tracked
from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.core.logging import get_logger
from app.integrations.aws.s3 import S3Storage
from app.models.enums import AgentName, AgentStatus
from app.services.grading import GradingService, GradingUnavailable, build_graders
from app.workers.queue import ArqJobQueue

log = get_logger(__name__)


async def grade_listing_job(ctx: dict[str, Any], listing_id: str, execution_id: str | None = None) -> None:
    settings = get_settings()
    storage = ctx.get("storage") or S3Storage(settings)
    graders = ctx.get("graders") or build_graders(settings)
    queue = ctx.get("queue") or ArqJobQueue(settings)
    attempt = int(ctx.get("job_try", 1))
    final = attempt >= settings.GRADING_MAX_ATTEMPTS
    async with get_sessionmaker()() as session:
        svc = GradingService(session, settings, storage, graders)
        produced: dict[str, Any] = {}

        async def fn() -> AgentOutcome:
            res = await svc.grade_listing(uuid.UUID(listing_id), final_attempt=final)
            if res is None:
                return AgentOutcome(AgentStatus.REVIEW_REQUIRED if final else AgentStatus.COMPLETED,
                                    "no result: listing not analyzing, or AI unavailable and routed to manual review")
            produced["result"] = res
            return AgentOutcome(
                AgentStatus.REVIEW_REQUIRED if res.requires_review else AgentStatus.COMPLETED,
                f"grade {res.grade.value}, confidence {res.confidence:.2f}" + (" (cached)" if res.from_cache else ""),
                res.provider.value, res.fallback_used,
                [{"tool": "vision_grade", "ok": True, "provider": res.provider.value, "cached": res.from_cache}])

        try:
            await run_tracked(session, uuid.UUID(execution_id) if execution_id else None, fn, attempt=attempt,
                              max_attempts=settings.GRADING_MAX_ATTEMPTS)
        except GradingUnavailable as exc:
            log.warning("grading_retry", listing_id=listing_id, attempt=attempt)
            raise Retry(defer=attempt * 30) from exc
        res = produced.get("result")
        if res is not None:  # grading.completed -> Smart Pricing Agent (idempotent per grading result)
            await dispatch(session, queue, agent=AgentName.SMART_PRICING, job_name="price_listing_job",
                           trigger_type="grading.completed", entity_type="listing", entity_id=listing_id,
                           job_args=(listing_id, str(res.id)), idempotency_key=f"pricing:{res.id}")
