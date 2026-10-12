import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import MatchStatus
from app.models.match import Match


class MatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, match_id: uuid.UUID) -> Match | None:
        return await self.session.get(Match, match_id)

    async def for_requirement(self, requirement_id: uuid.UUID) -> list[Match]:
        return list((await self.session.scalars(select(Match).where(
            Match.requirement_id == requirement_id, Match.status != MatchStatus.DISMISSED)
            .order_by(Match.rank, Match.id))).all())
