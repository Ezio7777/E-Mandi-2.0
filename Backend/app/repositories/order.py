import uuid
from datetime import datetime

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrderStatus, UserRole
from app.models.order import Order


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, order_id: uuid.UUID) -> Order | None:
        """Always re-reads (populate_existing) so server-side columns and relationships are fresh."""
        return await self.session.scalar(select(Order).where(Order.id == order_id).execution_options(populate_existing=True))

    async def get_for_update(self, order_id: uuid.UUID) -> Order | None:
        return await self.session.scalar(select(Order).where(Order.id == order_id).with_for_update(of=Order)
                                         .execution_options(populate_existing=True))

    async def list_for(self, user_id: uuid.UUID, role: UserRole, status: OrderStatus | None,
                       cursor: tuple[datetime, uuid.UUID] | None, limit: int) -> list[Order]:
        stmt = select(Order)
        if role == UserRole.BUYER:
            stmt = stmt.where(Order.buyer_id == user_id)
        elif role == UserRole.FARMER:
            stmt = stmt.where(Order.farmer_id == user_id)
        if status:
            stmt = stmt.where(Order.status == status)
        if cursor:
            stmt = stmt.where(tuple_(Order.created_at, Order.id) < tuple_(cursor[0], cursor[1]))
        return list((await self.session.scalars(stmt.order_by(Order.created_at.desc(), Order.id.desc()).limit(limit + 1))).all())

    async def lock_expired(self, now: datetime, limit: int) -> list[Order]:
        """Expired unpaid reservations; SKIP LOCKED so concurrent sweepers/payments never block each other."""
        stmt = (select(Order).where(Order.status.in_([OrderStatus.RESERVED, OrderStatus.PAYMENT_PENDING]),
                                    Order.reservation_expires_at < now)
                .order_by(Order.reservation_expires_at).limit(limit).with_for_update(of=Order, skip_locked=True)
                .execution_options(populate_existing=True))
        return list((await self.session.scalars(stmt)).all())
