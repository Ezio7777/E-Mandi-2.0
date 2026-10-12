"""Read-only context collection for the Fraud & Risk Agent. Plain SELECTs; returns the pure-rule contexts."""
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.fraud_risk.rules import ListingCtx, OrderCtx, PaymentCtx
from app.core.config import Settings
from app.models.audit_log import AuditLog
from app.models.crop_grading_result import CropGradingResult
from app.models.enums import PaymentStatus
from app.models.listing import Listing
from app.models.listing_image import ListingImage
from app.models.order import Order
from app.models.payment import Payment
from app.models.user import User
from app.services.pricing import NoMarketDataError, PricingService
from app.utils.time import utcnow


async def listing_context(session: AsyncSession, listing_id: uuid.UUID) -> ListingCtx | None:
    l = await session.get(Listing, listing_id, populate_existing=True)
    if l is None:
        return None
    now = utcnow()
    try:
        ref: int | None = (await PricingService(session).recommend(crop=l.crop_name, location=l.location, grade=None,
                                                                   quantity_kg=l.quantity_kg)).reference_paise
    except NoMarketDataError:
        ref = None
    edits = await session.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.entity_type == "listing", AuditLog.entity_id == str(l.id), AuditLog.action == "listing.updated",
        AuditLog.timestamp >= now - timedelta(hours=1))) or 0
    shas = list((await session.scalars(select(ListingImage.sha256).where(ListingImage.listing_id == l.id))).all())
    dup_ids: list[uuid.UUID] = []
    dup_sha: str | None = None
    if shas:
        rows = (await session.execute(select(Listing.id, ListingImage.sha256).join(ListingImage, ListingImage.listing_id == Listing.id)
                                      .where(ListingImage.sha256.in_(shas), Listing.farmer_id != l.farmer_id).limit(20))).all()
        dup_ids = list(dict.fromkeys(r[0] for r in rows))
        dup_sha = rows[0][1] if rows else None
    g = await session.scalar(select(CropGradingResult).where(CropGradingResult.listing_id == l.id)
                             .order_by(CropGradingResult.created_at.desc()).limit(1))
    return ListingCtx(l.id, l.farmer_id, l.crop_name, l.quantity_kg, l.base_price_paise, ref, int(edits), now, dup_ids, dup_sha,
                      g.id if g else None, g.confidence if g else None, bool(g.requires_review) if g else False)


async def order_context(session: AsyncSession, order_id: uuid.UUID) -> OrderCtx | None:
    o = await session.get(Order, order_id, populate_existing=True)
    if o is None:
        return None
    now = utcnow()
    buyer = await session.get(User, o.buyer_id)
    age_h = (now - buyer.created_at).total_seconds() / 3600 if buyer else 1e9
    n = await session.scalar(select(func.count()).select_from(Order).where(
        Order.buyer_id == o.buyer_id, Order.created_at >= now - timedelta(hours=1))) or 0
    return OrderCtx(o.id, o.buyer_id, o.total_amount_paise, age_h, int(n), now)


async def payment_context(session: AsyncSession, payment_id: uuid.UUID, settings: Settings) -> PaymentCtx | None:
    p = await session.get(Payment, payment_id, populate_existing=True)
    if p is None:
        return None
    now = utcnow()
    n = await session.scalar(select(func.count()).select_from(Payment).where(
        Payment.payer_id == p.payer_id, Payment.status == PaymentStatus.FAILED, Payment.updated_at >= now - timedelta(hours=24))) or 0
    return PaymentCtx(p.id, p.payer_id, p.order_id, int(n), now)
