"""Job-status lookups (agent_executions) with ownership checks, mapped to the camelCase contract."""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.agent_execution import AgentExecution
from app.models.enums import AgentName, UserRole
from app.models.buyer_requirement import BuyerRequirement
from app.models.listing import Listing
from app.models.user import User
from app.schemas.pricing import JobStatusOut


async def get_job_for_user(session: AsyncSession, user: User, job_id: uuid.UUID, agent: AgentName) -> AgentExecution:
    ex = await session.get(AgentExecution, job_id, populate_existing=True)
    if ex is None or ex.agent_name != agent:
        raise NotFoundError("Job not found")
    if user.role != UserRole.ADMIN:
        eid = uuid.UUID(ex.related_entity_id or uuid.UUID(int=0).hex)
        col, model = (BuyerRequirement.buyer_id, BuyerRequirement) if ex.related_entity_type == "requirement" else (Listing.farmer_id, Listing)
        owner = await session.scalar(select(col).where(model.id == eid))
        if owner != user.id:
            raise NotFoundError("Job not found")  # same response as a missing job: existence is not leaked
    return ex


def job_out(ex: AgentExecution) -> dict:
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    return JobStatusOut(
        job_id=str(ex.id), agent=ex.agent_name.value, status=ex.status.value,  # type: ignore[arg-type]
        listing_id=ex.related_entity_id if ex.related_entity_type == "listing" else None, provider=ex.provider,
        fallback_used=ex.fallback_used, summary=ex.summary, attempt=ex.attempt, started_at=iso(ex.started_at),
        completed_at=iso(ex.completed_at), duration_ms=ex.duration_ms).model_dump()
