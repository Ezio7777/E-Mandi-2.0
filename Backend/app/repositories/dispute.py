import uuid
from datetime import datetime

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dispute import Dispute
from app.models.enums import DisputeStatus
from app.models.order import Order


class DisputeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, dispute_id: uuid.UUID) -> Dispute | None:
        return await self.session.get(Dispute, dispute_id, populate_existing=True)

    async def get_for_update(self, dispute_id: uuid.UUID) -> Dispute | None:
        return await self.session.get(Dispute, dispute_id, with_for_update=True, populate_existing=True)

    async def for_order(self, order_id: uuid.UUID) -> list[Dispute]:
        return list((await self.session.scalars(select(Dispute).where(Dispute.order_id == order_id))).all())

    async def list_for(self, user_id: uuid.UUID | None, status: DisputeStatus | None, cursor: tuple[datetime, uuid.UUID] | None,
                       limit: int) -> list[Dispute]:
        """user_id=None => all disputes (admin). Otherwise disputes on orders where the user is buyer or farmer."""
        stmt = select(Dispute).join(Order, Order.id == Dispute.order_id)
        if user_id is not None:
            stmt = stmt.where((Order.buyer_id == user_id) | (Order.farmer_id == user_id))
        if status:
            stmt = stmt.where(Dispute.status == status)
        if cursor:
            stmt = stmt.where(tuple_(Dispute.created_at, Dispute.id) < tuple_(cursor[0], cursor[1]))
        return list((await self.session.scalars(stmt.order_by(Dispute.created_at.desc(), Dispute.id.desc()).limit(limit + 1)
                                                .execution_options(populate_existing=True))).all())
