import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, row: Session) -> Session:
        self.session.add(row)
        await self.session.flush()
        return row

    async def get(self, session_id: uuid.UUID) -> Session | None:
        return await self.session.get(Session, session_id)

    async def get_by_token_hash(self, token_hash: str, *, for_update: bool = False) -> Session | None:
        stmt = select(Session).where(Session.refresh_token_hash == token_hash)
        if for_update:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def revoke_family(self, family_id: uuid.UUID, now: datetime) -> None:
        await self.session.execute(update(Session).where(
            Session.family_id == family_id, Session.revoked_at.is_(None)).values(revoked_at=now))

    async def revoke_all_for_user(self, user_id: uuid.UUID, now: datetime) -> None:
        await self.session.execute(update(Session).where(
            Session.user_id == user_id, Session.revoked_at.is_(None)).values(revoked_at=now))
