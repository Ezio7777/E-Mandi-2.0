import uuid
from datetime import datetime

from pydantic import ConfigDict, Field

from app.schemas.common import CamelBlob, CamelModel


class AuditOut(CamelModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: uuid.UUID
    actor_id: uuid.UUID | None
    actor_role: str | None
    action: str
    entity_type: str
    entity_id: str | None
    timestamp: datetime
    metadata: CamelBlob = Field(validation_alias="meta")
    previous_state: CamelBlob | None
    new_state: CamelBlob | None
    ip_address: str | None
    request_id: str | None


class AuditPage(CamelModel):
    items: list[AuditOut]
    next_cursor: str | None


class ActionCount(CamelModel):
    action: str
    count: int


class AuditTimeline(CamelModel):
    entity_type: str
    entity_id: str
    events: list[AuditOut]
    truncated: bool
