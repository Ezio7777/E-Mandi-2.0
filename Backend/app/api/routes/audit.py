import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import SessionDep, require_roles
from app.core.errors import DomainValidationError, NotFoundError
from app.core.rate_limit import rate_limit
from app.models.enums import UserRole
from app.repositories.audit import AuditFilters, AuditRepository
from app.schemas.audit import ActionCount, AuditOut, AuditPage, AuditTimeline
from app.schemas.common import Envelope
from app.utils.pagination import decode_cursor, encode_cursor
from app.utils.time import utcnow

router = APIRouter(prefix="/audit", tags=["audit"], dependencies=[Depends(require_roles(UserRole.ADMIN)),
                                                                   Depends(rate_limit("audit", 120, 60, per_user=True))])
MAX_TIMELINE = 500
Short = Annotated[str | None, Query(max_length=120)]


@router.get("/logs", response_model=Envelope[AuditPage])
async def search_logs(session: SessionDep, actor_id: uuid.UUID | None = None, action: Short = None, action_prefix: Short = None,
                      entity_type: Annotated[str | None, Query(max_length=50)] = None, entity_id: Annotated[str | None, Query(max_length=64)] = None,
                      request_id: Annotated[str | None, Query(max_length=64)] = None, since: datetime | None = None,
                      until: datetime | None = None, cursor: Annotated[str | None, Query(max_length=300)] = None,
                      limit: Annotated[int, Query(ge=1, le=100)] = 25):
    """Newest first. Read-only: the audit log is append-only and has no mutation endpoints."""
    if since and until and since >= until:
        raise DomainValidationError("`since` must be before `until`", details=[{"field": "since", "message": "must be before until"}])
    f = AuditFilters(actor_id, action, action_prefix, entity_type, entity_id, request_id, since, until)
    rows = await AuditRepository(session).search(f, decode_cursor(cursor) if cursor else None, limit)
    more, rows = len(rows) > limit, rows[:limit]
    return Envelope(data=AuditPage(items=[AuditOut.model_validate(r) for r in rows],
                                   next_cursor=encode_cursor(rows[-1].timestamp, rows[-1].id) if more else None))


@router.get("/logs/{log_id}", response_model=Envelope[AuditOut])
async def get_log(log_id: uuid.UUID, session: SessionDep):
    row = await AuditRepository(session).get(log_id)
    if row is None:
        raise NotFoundError("Audit event not found")
    return Envelope(data=AuditOut.model_validate(row))


@router.get("/entities/{entity_type}/{entity_id}", response_model=Envelope[AuditTimeline])
async def entity_timeline(entity_type: str, entity_id: str, session: SessionDep):
    """Everything that ever happened to one entity, oldest first (e.g. a listing, order, payment, dispute or user)."""
    rows = await AuditRepository(session).timeline(entity_type[:50], entity_id[:64], MAX_TIMELINE)
    return Envelope(data=AuditTimeline(entity_type=entity_type, entity_id=entity_id, truncated=len(rows) > MAX_TIMELINE,
                                       events=[AuditOut.model_validate(r) for r in rows[:MAX_TIMELINE]]))


@router.get("/actions", response_model=Envelope[list[ActionCount]])
async def action_counts(session: SessionDep, days: Annotated[int | None, Query(ge=1, le=365)] = None):
    """Distinct audit actions with counts (drives filter dropdowns)."""
    since = utcnow() - timedelta(days=days) if days else None
    return Envelope(data=[ActionCount(action=a, count=n) for a, n in await AuditRepository(session).action_counts(since)])
