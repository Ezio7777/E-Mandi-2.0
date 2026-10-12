"""Audit recorder. record() only ADDS a row to the caller's session, so it commits (or rolls back)
atomically with the business action. Query/reporting API is added in Stage 16."""
import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.enums import UserRole


@dataclass(frozen=True)
class RequestContext:
    ip: str | None = None
    user_agent: str | None = None


@dataclass(frozen=True)
class Actor:
    id: uuid.UUID | None
    role: UserRole | str | None = None

    @property
    def role_value(self) -> str | None:
        return self.role.value if isinstance(self.role, UserRole) else self.role


SYSTEM_ACTOR = Actor(id=None, role="SYSTEM")


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def record(self, *, action: str, entity_type: str, entity_id: Any = None, actor: Actor | None = None,
               metadata: dict | None = None, previous_state: dict | None = None,
               new_state: dict | None = None, ip: str | None = None) -> AuditLog:
        row = AuditLog(
            actor_id=actor.id if actor else None,
            actor_role=actor.role_value if actor else None,
            action=action, entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            meta=metadata or {}, previous_state=previous_state, new_state=new_state, ip_address=ip,
            request_id=structlog.contextvars.get_contextvars().get("request_id"),
        )
        self.session.add(row)
        return row
