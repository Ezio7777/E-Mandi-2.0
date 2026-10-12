import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        return await self.session.scalar(select(User).where(User.email == email.lower()))

    async def get_by_phone(self, phone: str) -> User | None:
        return await self.session.scalar(select(User).where(User.phone == phone))

    async def get_by_google_sub(self, sub: str) -> User | None:
        return await self.session.scalar(select(User).where(User.google_sub == sub))

    async def add(self, user: User) -> User:
        self.session.add(user)
        await self.session.flush()
        return user
