"""Admin analytics. Plain aggregate SELECTs over the source tables (no separate store to drift out of sync). The overview is
cached in Redis for ANALYTICS_CACHE_SECONDS and can be refreshed by the arq job (workers/analytics_jobs.py)."""
from datetime import date, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.models.anomaly_event import AnomalyEvent
from app.models.dispute import Dispute
from app.models.enums import (
    AnomalyStatus,
    DisputeStatus,
    ListingStatus,
    OrderStatus,
    PaymentStatus,
    PendingActionStatus,
    RefundStatus,
)
from app.models.listing import Listing
from app.models.order import Order
from app.models.payment import Payment
from app.models.pending_action import PendingAction
from app.models.refund import Refund
from app.models.user import User
from app.schemas.analytics import (
    ListingsStat,
    Metric,
    OrdersStat,
    OverviewOut,
    PaymentsStat,
    RiskStat,
    SeriesPoint,
    TimeseriesOut,
    TopCrop,
    TopCropsOut,
    UsersStat,
)
from app.utils.money import paise_to_rupees
from app.utils.time import utcnow

log = get_logger(__name__)
GMV_STATUSES = [OrderStatus.PAID, OrderStatus.CONFIRMED, OrderStatus.IN_FULFILLMENT, OrderStatus.COMPLETED, OrderStatus.DISPUTED]
OPEN_DISPUTES = [DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW, DisputeStatus.EVIDENCE_REQUESTED, DisputeStatus.REFUND_REQUIRED]
CACHE_KEY = "analytics:overview:{days}"


def _group(rows: Any) -> dict[str, int]:
    return {(k.value if hasattr(k, "value") else str(k)): int(n) for k, n in rows}


class AnalyticsService:
    def __init__(self, session: AsyncSession, settings: Settings, redis: Redis | None = None) -> None:
        self.session, self.settings, self.redis = session, settings, redis

    async def _count(self, stmt: Any) -> int:
        return int(await self.session.scalar(stmt) or 0)

    # ------------------------------------------------------------------ overview (cached)
    async def overview(self, days: int, *, refresh: bool = False) -> tuple[OverviewOut, bool]:
        key = CACHE_KEY.format(days=days)
        if self.redis is not None and not refresh:
            try:
                raw = await self.redis.get(key)
                if raw:
                    return OverviewOut.model_validate_json(raw), True
            except Exception as exc:
                log.warning("analytics_cache_read_failed", error_type=type(exc).__name__)
        out = await self.compute_overview(days)
        await self.store(out)
        return out, False

    async def store(self, out: OverviewOut) -> None:
        if self.redis is None:
            return
        try:
            await self.redis.set(CACHE_KEY.format(days=out.window_days), out.model_dump_json(), ex=self.settings.ANALYTICS_CACHE_SECONDS)
        except Exception as exc:
            log.warning("analytics_cache_write_failed", error_type=type(exc).__name__)

    async def compute_overview(self, days: int) -> OverviewOut:
        s, now = self.session, utcnow()
        since = now - timedelta(days=days)
        users = UsersStat(
            by_role=_group((await s.execute(select(User.role, func.count()).group_by(User.role))).all()),
            new_in_window=await self._count(select(func.count()).select_from(User).where(User.created_at >= since)),
            banned=await self._count(select(func.count()).select_from(User).where(User.banned_at.is_not(None))))
        listings = ListingsStat(
            by_status=_group((await s.execute(select(Listing.status, func.count()).group_by(Listing.status))).all()),
            new_in_window=await self._count(select(func.count()).select_from(Listing).where(Listing.created_at >= since)),
            awaiting_grading_review=await self._count(select(func.count()).select_from(Listing).where(Listing.status == ListingStatus.REVIEW_REQUIRED)))
        gmv_n, gmv_sum = (await s.execute(select(func.count(), func.coalesce(func.sum(Order.total_amount_paise), 0)).where(
            Order.created_at >= since, Order.status.in_(GMV_STATUSES)))).one()
        orders = OrdersStat(
            by_status=_group((await s.execute(select(Order.status, func.count()).group_by(Order.status))).all()),
            new_in_window=await self._count(select(func.count()).select_from(Order).where(Order.created_at >= since)),
            gmv=paise_to_rupees(int(gmv_sum)), average_order_value=paise_to_rupees(int(gmv_sum) // int(gmv_n)) if gmv_n else None)
        paid = [PaymentStatus.SUCCESS, PaymentStatus.REFUND_REQUESTED, PaymentStatus.REFUNDED]
        ok = await self._count(select(func.count()).select_from(Payment).where(Payment.created_at >= since, Payment.status.in_(paid)))
        bad = await self._count(select(func.count()).select_from(Payment).where(Payment.created_at >= since, Payment.status == PaymentStatus.FAILED))
        refunded = int(await s.scalar(select(func.coalesce(func.sum(Refund.amount_paise), 0)).where(
            Refund.created_at >= since, Refund.status == RefundStatus.COMPLETED)) or 0)
        payments = PaymentsStat(succeeded=ok, failed=bad, success_rate=round(ok / (ok + bad), 3) if ok + bad else None,
                                refunded=paise_to_rupees(refunded))
        risk = RiskStat(
            disputes_open=await self._count(select(func.count()).select_from(Dispute).where(Dispute.status.in_(OPEN_DISPUTES))),
            anomalies_open_by_severity=_group((await s.execute(select(AnomalyEvent.severity, func.count()).where(
                AnomalyEvent.status.in_([AnomalyStatus.FLAGGED_FOR_REVIEW, AnomalyStatus.ACTION_REQUESTED])).group_by(AnomalyEvent.severity))).all()),
            pending_approvals=await self._count(select(func.count()).select_from(PendingAction).where(PendingAction.status == PendingActionStatus.PENDING)))
        return OverviewOut(window_days=days, generated_at=now, users=users, listings=listings, orders=orders, payments=payments, risk=risk)

    # ------------------------------------------------------------------ time series
    async def timeseries(self, metric: Metric, days: int) -> TimeseriesOut:
        today = utcnow().date()
        first = today - timedelta(days=days - 1)
        day = cast(func.timezone("UTC", {"signups": User.created_at, "listings": Listing.created_at, "orders": Order.created_at,
                                         "gmv": Order.created_at, "payments_failed": Payment.created_at, "disputes": Dispute.created_at}[metric]), Date)
        if metric == "gmv":
            stmt = select(day, func.coalesce(func.sum(Order.total_amount_paise), 0)).where(Order.status.in_(GMV_STATUSES))
        else:
            model = {"signups": User, "listings": Listing, "orders": Order, "payments_failed": Payment, "disputes": Dispute}[metric]
            stmt = select(day, func.count()).select_from(model)
            if metric == "payments_failed":
                stmt = stmt.where(Payment.status == PaymentStatus.FAILED)
        col = {"signups": User.created_at, "listings": Listing.created_at, "orders": Order.created_at, "gmv": Order.created_at,
               "payments_failed": Payment.created_at, "disputes": Dispute.created_at}[metric]
        rows = (await self.session.execute(stmt.where(col >= utcnow() - timedelta(days=days)).group_by(day))).all()
        by_day: dict[date, float] = {d: (float(paise_to_rupees(int(v))) if metric == "gmv" else float(v)) for d, v in rows}
        pts = [SeriesPoint(day=first + timedelta(days=i), value=by_day.get(first + timedelta(days=i), 0.0)) for i in range(days)]
        return TimeseriesOut(metric=metric, unit="rupees" if metric == "gmv" else "count", days=days, points=pts,
                             total=round(sum(p.value for p in pts), 2))

    async def top_crops(self, days: int, limit: int) -> TopCropsOut:
        since = utcnow() - timedelta(days=days)
        stmt = (select(Listing.crop_name, func.count(), func.coalesce(func.sum(Listing.quantity_kg), 0), func.avg(Listing.base_price_paise))
                .where(Listing.created_at >= since, Listing.status.not_in([ListingStatus.DRAFT, ListingStatus.ARCHIVED]))
                .group_by(Listing.crop_name).order_by(func.count().desc(), Listing.crop_name).limit(limit))
        return TopCropsOut(window_days=days, items=[TopCrop(crop=c, listings=int(n), total_kg=float(kg), average_price=paise_to_rupees(round(avg)))
                                                   for c, n, kg, avg in (await self.session.execute(stmt)).all()])
