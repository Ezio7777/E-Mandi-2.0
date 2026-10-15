"""Notification records + read side. add()/notify_admins() only ADD rows to the caller's transaction (so a notification
commits or rolls back with the action that caused it). Every read query is scoped to user_id: there is no way to read
another user's notifications."""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import transactional
from app.core.errors import NotFoundError
from app.models.enums import NotificationType, UserRole
from app.models.notification import Notification
from app.models.user import User
from app.utils.time import utcnow


class NotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---- write side (caller owns the transaction)
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

    # ---- read side
    async def list_for(self, user_id: uuid.UUID, unread_only: bool, cursor: tuple[datetime, uuid.UUID] | None,
                       limit: int) -> list[Notification]:
        stmt = select(Notification).where(Notification.user_id == user_id)
        if unread_only:
            stmt = stmt.where(Notification.is_read.is_(False))
        if cursor:
            stmt = stmt.where(tuple_(Notification.created_at, Notification.id) < tuple_(cursor[0], cursor[1]))
        stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit + 1)
        return list((await self.session.scalars(stmt)).all())

    async def unread_count(self, user_id: uuid.UUID) -> int:
        return await self.session.scalar(select(func.count()).select_from(Notification).where(
            Notification.user_id == user_id, Notification.is_read.is_(False))) or 0

    async def mark_read(self, user_id: uuid.UUID, notification_id: uuid.UUID) -> None:
        async with transactional(self.session):
            n = await self.session.scalar(select(Notification).where(
                Notification.id == notification_id, Notification.user_id == user_id).with_for_update())
            if n is None:
                raise NotFoundError("Notification not found")  # identical response for other users' notifications
            if not n.is_read:
                n.is_read, n.read_at = True, utcnow()

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        async with transactional(self.session):
            res = await self.session.execute(update(Notification).where(
                Notification.user_id == user_id, Notification.is_read.is_(False)).values(is_read=True, read_at=utcnow()))
        return getattr(res, "rowcount", 0) or 0

    async def newer_than(self, user_id: uuid.UUID, after: tuple[datetime, uuid.UUID], limit: int = 50) -> list[Notification]:
        stmt = select(Notification).where(
            Notification.user_id == user_id,
            tuple_(Notification.created_at, Notification.id) > tuple_(after[0], after[1]),
        ).order_by(Notification.created_at, Notification.id).limit(limit)
        return list((await self.session.scalars(stmt)).all())
