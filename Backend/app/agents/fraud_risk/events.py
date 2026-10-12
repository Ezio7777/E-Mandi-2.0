"""Business event -> RiskAssessmentJob. Emission must NEVER break the business request that caused it."""
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runtime import dispatch
from app.core.logging import get_logger
from app.models.enums import AgentName
from app.workers.queue import JobQueue

log = get_logger(__name__)
JOB = "assess_risk_job"
LISTING_EVENTS = {"listing.created", "listing.updated", "listing.submitted", "grading.completed", "image.uploaded"}
EVENT_ENTITY = {**{e: "listing" for e in LISTING_EVENTS}, "order.created": "order", "payment.failed": "payment"}


async def emit_risk_event(session: AsyncSession, queue: JobQueue | None, event_type: str, entity_id: uuid.UUID | str,
                          *, idempotency_key: str | None = None) -> Any:
    if queue is None or event_type not in EVENT_ENTITY:
        return None
    entity_type = EVENT_ENTITY[event_type]
    try:
        return await dispatch(session, queue, agent=AgentName.FRAUD_RISK, job_name=JOB, trigger_type=event_type, entity_type=entity_type,
                              entity_id=entity_id, job_args=(event_type, entity_type, str(entity_id)), idempotency_key=idempotency_key)
    except Exception as exc:  # noqa: BLE001
        log.warning("risk_event_emit_failed", event=event_type, error_type=type(exc).__name__)
        return None
