import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.buyer_requirement import BuyerRequirement


class RequirementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, requirement_id: uuid.UUID) -> BuyerRequirement | None:
        return await self.session.get(BuyerRequirement, requirement_id)

    async def get_for_update(self, requirement_id: uuid.UUID) -> BuyerRequirement | None:
        return await self.session.scalar(select(BuyerRequirement).where(BuyerRequirement.id == requirement_id)
                                         .with_for_update().execution_options(populate_existing=True))

    async def list_for_buyer(self, buyer_id: uuid.UUID, limit: int = 100) -> list[BuyerRequirement]:
        return list((await self.session.scalars(select(BuyerRequirement).where(BuyerRequirement.buyer_id == buyer_id)
                                                .order_by(BuyerRequirement.created_at.desc()).limit(limit))).all())
