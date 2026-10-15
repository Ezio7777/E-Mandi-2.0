import uuid
from datetime import datetime

from pydantic import ConfigDict

from app.models.enums import NotificationType
from app.schemas.common import CamelBlob, CamelModel


class NotificationOut(CamelModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    type: NotificationType
    title: str
    body: str
    data: CamelBlob
    is_read: bool
    read_at: datetime | None
    created_at: datetime


class NotificationPage(CamelModel):
    items: list[NotificationOut]
    next_cursor: str | None
    unread_count: int


class UnreadCount(CamelModel):
    unread_count: int


class MarkedRead(CamelModel):
    marked: int
