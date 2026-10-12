import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PaymentStatus, RefundStatus
from app.models.payment import Payment
from app.models.refund import Refund


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, payment_id: uuid.UUID) -> Payment | None:
        return await self.session.get(Payment, payment_id, populate_existing=True)

    async def get_for_update(self, payment_id: uuid.UUID) -> Payment | None:
        return await self.session.get(Payment, payment_id, with_for_update=True, populate_existing=True)

    async def by_key(self, scoped_key: str) -> Payment | None:
        return await self.session.scalar(select(Payment).where(Payment.idempotency_key == scoped_key)
                                         .execution_options(populate_existing=True))

    async def by_provider_order(self, provider_order_id: str) -> Payment | None:
        return await self.session.scalar(select(Payment).where(Payment.provider_order_id == provider_order_id))

    async def by_provider_payment(self, provider_payment_id: str) -> Payment | None:
        return await self.session.scalar(select(Payment).where(Payment.provider_payment_id == provider_payment_id).limit(1))

    async def active_for_order(self, order_id: uuid.UUID) -> Payment | None:
        return await self.session.scalar(select(Payment).where(
            Payment.order_id == order_id, Payment.status.in_([PaymentStatus.CREATED, PaymentStatus.PENDING]))
            .order_by(Payment.created_at.desc()).limit(1).execution_options(populate_existing=True))

    async def count_for_order(self, order_id: uuid.UUID) -> int:
        return await self.session.scalar(select(func.count()).select_from(Payment).where(Payment.order_id == order_id)) or 0

    async def other_success_for_order(self, order_id: uuid.UUID, exclude: uuid.UUID) -> Payment | None:
        return await self.session.scalar(select(Payment).where(
            Payment.order_id == order_id, Payment.id != exclude,
            Payment.status.in_([PaymentStatus.SUCCESS, PaymentStatus.REFUND_REQUESTED, PaymentStatus.REFUNDED])).limit(1))

    async def for_order(self, order_id: uuid.UUID) -> list[Payment]:
        return list((await self.session.scalars(select(Payment).where(Payment.order_id == order_id)
                                                .order_by(Payment.created_at.desc()))).all())

    # ---- refunds
    async def get_refund(self, refund_id: uuid.UUID) -> Refund | None:
        return await self.session.get(Refund, refund_id, populate_existing=True)

    async def refund_by_provider_id(self, provider_refund_id: str) -> Refund | None:
        return await self.session.scalar(select(Refund).where(Refund.provider_refund_id == provider_refund_id))

    async def refunds_for(self, payment_id: uuid.UUID) -> list[Refund]:
        return list((await self.session.scalars(select(Refund).where(Refund.payment_id == payment_id)
                                                .order_by(Refund.created_at).execution_options(populate_existing=True))).all())

    async def refund_total(self, payment_id: uuid.UUID, statuses: Sequence[RefundStatus]) -> int:
        total = await self.session.scalar(select(func.coalesce(func.sum(Refund.amount_paise), 0)).where(
            Refund.payment_id == payment_id, Refund.status.in_(list(statuses))))
        return int(total or 0)  # SUM(bigint) is NUMERIC in Postgres -> Decimal; money is always int paise
