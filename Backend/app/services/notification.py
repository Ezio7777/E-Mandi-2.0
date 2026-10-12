"""Notification records. add()/notify_admins() only ADD rows to the caller's transaction (API arrives in Stage 13)."""
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import NotificationType, UserRole
from app.models.notification import Notification
from app.models.user import User


class NotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, user_id: uuid.UUID, type_: NotificationType, title: str, body: str,
            data: dict[str, Any] | None = None) -> Notification:
        n = Notification(user_id=user_id, type=type_, title=title, body=body, data=data or {})
        self.session.add(n)
        return n

    async def notify_admins(self, type_: NotificationType, title: str, body: str,
                            data: dict[str, Any] | None = None) -> int:
        ids = (await self.session.scalars(
            select(User.id).where(User.role == UserRole.ADMIN, User.is_active.is_(True)))).all()
        for uid in ids:
            self.add(uid, type_, title, body, data)
        return len(ids)
