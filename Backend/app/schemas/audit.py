import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: uuid.UUID
    actor_id: uuid.UUID | None
    actor_role: str | None
    action: str
    entity_type: str
    entity_id: str | None
    timestamp: datetime
    metadata: dict[str, Any] = Field(validation_alias="meta")
    previous_state: dict[str, Any] | None
    new_state: dict[str, Any] | None
    ip_address: str | None
    request_id: str | None


class AuditPage(BaseModel):
    items: list[AuditOut]
    next_cursor: str | None


class ActionCount(BaseModel):
    action: str
    count: int


class AuditTimeline(BaseModel):
    entity_type: str
    entity_id: str
    events: list[AuditOut]
    truncated: bool
