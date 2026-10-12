import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.otp_challenge import OtpChallenge


class OtpRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, row: OtpChallenge) -> OtpChallenge:
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_for_update(self, challenge_id: uuid.UUID) -> OtpChallenge | None:
        return await self.session.scalar(
            select(OtpChallenge).where(OtpChallenge.id == challenge_id).with_for_update())
