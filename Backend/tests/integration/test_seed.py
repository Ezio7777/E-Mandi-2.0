"""Stage 22+: seed and reset scripts."""
from datetime import date

import pytest
from app.core.database import get_sessionmaker
from app.models.buyer_requirement import BuyerRequirement
from app.models.enums import ListingStatus
from app.models.listing import Listing
from app.models.market_report import MarketReport
from app.models.user import User
from scripts.reset_seed import SeedInUse, reset
from scripts.seed import SAMPLE_SOURCE, embed, seed
from sqlalchemy import func, select

from tests.integration.test_matching_agent import buyer
from tests.integration.test_orders import place

TODAY = date(2026, 10, 12)


async def count(db, model, *where):
    return await db.scalar(select(func.count()).select_from(model).where(*where))


async def test_seed_creates_expected_data_and_is_idempotent(app_ctx, db):
    first = await seed(get_sessionmaker(), "SeedPass123", TODAY)
    assert (first.users, first.listings, first.requirements) == (10, 8, 3)
    assert first.market_reports == 6 * 3 * 30
    again = await seed(get_sessionmaker(), "SeedPass123", TODAY)
    assert (again.users, again.market_reports, again.listings, again.requirements) == (0, 0, 0, 0)
    assert await count(db, Listing, Listing.status == ListingStatus.ACTIVE) == 8
    assert await count(db, MarketReport, MarketReport.is_sample.is_(True), MarketReport.source == SAMPLE_SOURCE) == 540
    demo = (await db.scalars(select(User).where(User.is_demo.is_(True)))).all()
    assert len(demo) == 3 and all(u.password_hash is None for u in demo)  # demo accounts cannot password-login


async def test_seeded_accounts_can_log_in_and_data_is_realistic(app_ctx, client, db):
    await seed(get_sessionmaker(), "SeedPass123", TODAY)
    r = await client.post("/api/v1/auth/login", json={"email": "ravi.gowda@seed.e-mandi.example.com", "password": "SeedPass123"})
    assert r.status_code == 200 and r.json()["data"]["user"]["role"] == "FARMER"
    prices = (await db.scalars(select(MarketReport.average_price_paise))).all()
    assert min(prices) > 1000 and max(prices) < 5000  # +-5 % wobble around plausible per-kg bases


async def test_seed_embeds_reports_and_listings_are_matchable(app_ctx, db):
    await seed(get_sessionmaker(), "SeedPass123", TODAY)
    assert await embed(app_ctx.state.__dict__.get("settings") or __import__("app.core.config", fromlist=["get_settings"]).get_settings()) == 540
    assert await count(db, MarketReport, MarketReport.embedding.is_(None)) == 0


async def test_reset_removes_seed_data_only(app_ctx, client, db):
    _, real_buyer = await buyer(client, 77)  # a real (non-seed) account must survive
    await seed(get_sessionmaker(), "SeedPass123", TODAY)
    out = await reset(get_sessionmaker())
    assert out["listings"] == 8 and out["requirements"] == 3 and out["market_reports"] == 540 and out["users"] >= 1
    assert await count(db, Listing) == 0 and await count(db, BuyerRequirement) == 0 and await count(db, MarketReport) == 0
    assert await db.get(User, real_buyer) is not None


async def test_reset_aborts_when_orders_exist(app_ctx, client, db):
    await seed(get_sessionmaker(), "SeedPass123", TODAY)
    bh, _ = await buyer(client, 78)
    lid = (await db.scalars(select(Listing.id).limit(1))).first()
    assert (await place(client, bh, lid, 10)).status_code == 201
    with pytest.raises(SeedInUse):
        await reset(get_sessionmaker())
    assert await count(db, Listing) == 8


async def test_scripts_refuse_production(monkeypatch):
    import scripts.reset_seed as rs
    import scripts.seed as sd
    from app.core.config import get_settings
    prod = get_settings().model_copy(update={"ENVIRONMENT": "production"})
    for mod in (sd, rs):
        monkeypatch.setattr(mod, "get_settings", lambda prod=prod: prod)
    monkeypatch.setattr("sys.argv", ["seed"])
    with pytest.raises(SystemExit, match="production"):
        await sd.main()
    with pytest.raises(SystemExit, match="production"):
        await rs.main()
