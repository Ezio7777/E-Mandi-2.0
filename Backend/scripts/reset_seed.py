"""Removes what scripts/seed.py created (seed + demo accounts and their data, sample market reports). usage: python -m scripts.reset_seed
Safe by construction: refuses in production, and aborts untouched if any order references seed users (real activity happened - reset the
whole database instead). Users referenced by the append-only audit log cannot be deleted; they are deactivated and reported."""
import asyncio
import sys

from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.models.buyer_requirement import BuyerRequirement
from app.models.crop_grading_result import CropGradingResult
from app.models.listing import Listing
from app.models.market_report import MarketReport
from app.models.match import Match
from app.models.notification import Notification
from app.models.order import Order
from app.models.pricing_result import PricingResult
from app.models.session import Session
from app.models.user import User
from app.models.user_profile import UserProfile
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scripts.seed import SAMPLE_SOURCE, SEED_DOMAIN


class SeedInUse(Exception):
    pass


async def reset(sm: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    out = {"users": 0, "kept_users": 0, "market_reports": 0, "listings": 0, "requirements": 0}
    async with sm() as s:
        ids = list((await s.scalars(select(User.id).where(or_(User.email.like(f"%@{SEED_DOMAIN}"), User.is_demo.is_(True))))).all())
        if ids:
            if await s.scalar(select(func.count()).select_from(Order).where(or_(Order.buyer_id.in_(ids), Order.farmer_id.in_(ids)))):
                raise SeedInUse("orders reference the seed/demo users; reset the whole database instead")
            lids = list((await s.scalars(select(Listing.id).where(Listing.farmer_id.in_(ids)))).all())
            rids = list((await s.scalars(select(BuyerRequirement.id).where(BuyerRequirement.buyer_id.in_(ids)))).all())
            await s.rollback()  # end the read transaction opened by the selects above
            async with s.begin():
                await s.execute(delete(Match).where(or_(Match.listing_id.in_(lids), Match.requirement_id.in_(rids))))
                await s.execute(delete(PricingResult).where(PricingResult.listing_id.in_(lids)))
                await s.execute(delete(CropGradingResult).where(CropGradingResult.listing_id.in_(lids)))
                out["listings"] = (await s.execute(delete(Listing).where(Listing.id.in_(lids)))).rowcount or 0
                out["requirements"] = (await s.execute(delete(BuyerRequirement).where(BuyerRequirement.id.in_(rids)))).rowcount or 0
                await s.execute(delete(Notification).where(Notification.user_id.in_(ids)))
                await s.execute(delete(Session).where(Session.user_id.in_(ids)))
            for uid in ids:
                try:
                    async with s.begin():
                        await s.execute(delete(UserProfile).where(UserProfile.user_id == uid))
                        await s.execute(delete(User).where(User.id == uid))
                    out["users"] += 1
                except DBAPIError:  # referenced by the append-only audit log (or other history): keep, but disable
                    async with s.begin():
                        await s.execute(update(User).where(User.id == uid).values(is_active=False))
                    out["kept_users"] += 1
        await s.rollback()
        async with s.begin():
            out["market_reports"] = (await s.execute(delete(MarketReport).where(MarketReport.source == SAMPLE_SOURCE))).rowcount or 0
    return out


async def main() -> None:
    if get_settings().is_production:
        raise SystemExit("refusing to reset a production environment")
    try:
        res = await reset(get_sessionmaker())
    except SeedInUse as exc:
        raise SystemExit(f"aborted, nothing changed: {exc}") from exc
    print("removed:", ", ".join(f"{v} {k}" for k, v in res.items()))
    if res["kept_users"]:
        print("note: users referenced by the audit log were deactivated, not deleted")


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
