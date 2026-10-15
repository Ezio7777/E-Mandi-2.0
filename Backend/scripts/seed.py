"""Idempotent sample data for development, demos and staging.  usage: python -m scripts.seed [--password PW] [--allow-production]

Creates (only what is missing):
  * demo accounts used by POST /auth/demo (demo.farmer/buyer/admin@e-mandi.demo, is_demo=True, no password)
  * 4 farmers + 3 buyers (<name>@seed.e-mandi.example.com) with profiles and coordinates
  * ~30 days of SAMPLE mandi price reports (is_sample=True, source "SEED-SAMPLE") for 6 crops x 3 markets
  * ACTIVE listings and OPEN buyer requirements
Everything is labelled as sample data; nothing here is real market data. Refuses to run in production unless --allow-production."""
import argparse
import asyncio
import secrets
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.core.config import Settings, get_settings
from app.core.database import get_sessionmaker
from app.core.security import hash_password
from app.models.buyer_requirement import BuyerRequirement
from app.models.enums import AuthProvider, CropCategory, Grade, ListingStatus, RequirementStatus, UserRole
from app.models.listing import Listing
from app.models.market_report import MarketReport
from app.models.user import User
from app.models.user_profile import UserProfile
from app.services.auth import DEMO_ACCOUNTS
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

SEED_DOMAIN = "seed.e-mandi.example.com"
SAMPLE_SOURCE = "SEED-SAMPLE"

CITIES = {  # city: (state, lat, lon, mandi)
    "Bengaluru": ("Karnataka", 12.9716, 77.5946, "Yeshwanthpur APMC"),
    "Mysuru": ("Karnataka", 12.2958, 76.6394, "Bandipalya APMC"),
    "Hubballi": ("Karnataka", 15.3647, 75.1240, "Hubballi APMC"),
}
CROPS = {  # crop: (category, base average paise/kg)
    "Tomato": (CropCategory.VEGETABLE, 2800), "Onion": (CropCategory.VEGETABLE, 2200), "Potato": (CropCategory.VEGETABLE, 1900),
    "Banana": (CropCategory.FRUIT, 3200), "Wheat": (CropCategory.GRAIN, 2600), "Rice": (CropCategory.GRAIN, 3600),
}
FARMERS = [("Ravi Gowda", "Mysuru", "kn"), ("Lakshmi Devi", "Bengaluru", "kn"), ("Suresh Patil", "Hubballi", "hi"), ("Anita Kumari", "Bengaluru", "en")]
BUYERS = [("Fresh Basket Traders", "Bengaluru", "en"), ("Mysore Mart", "Mysuru", "kn"), ("North Karnataka Foods", "Hubballi", "hi")]


@dataclass
class SeedResult:
    users: int = 0
    market_reports: int = 0
    listings: int = 0
    requirements: int = 0


def slug(name: str) -> str:
    return name.lower().replace(" ", ".")


async def _user(s: AsyncSession, email: str, name: str, role: UserRole, *, city: str | None = None, lang: str = "en",
                password: str | None = None, demo: bool = False) -> tuple[User, bool]:
    existing = await s.scalar(select(User).where(User.email == email))
    if existing is not None:
        return existing, False
    u = User(email=email, full_name=name, role=role, auth_provider=AuthProvider.LOCAL, email_verified=True, is_demo=demo,
             password_hash=hash_password(password) if password else None)
    if city:
        state, lat, lon, _ = CITIES[city]
        u.profile = UserProfile(display_name=name, city=city, state=state, latitude=lat, longitude=lon, preferred_language=lang)
    else:
        u.profile = UserProfile(display_name=name, preferred_language=lang)
    s.add(u)
    await s.flush()
    return u, True


async def seed(sm: async_sessionmaker[AsyncSession], password: str, today: date | None = None) -> SeedResult:
    today, out = today or date.today(), SeedResult()
    async with sm() as s, s.begin():
        for kind, (email, role, name) in DEMO_ACCOUNTS.items():
            _, new = await _user(s, email, name, role, city="Bengaluru" if kind != "admin" else None, demo=True)
            out.users += new
        farmers, buyers = [], []
        for name, city, lang in FARMERS:
            u, new = await _user(s, f"{slug(name)}@{SEED_DOMAIN}", name, UserRole.FARMER, city=city, lang=lang, password=password)
            farmers.append((u, city))
            out.users += new
        for name, city, lang in BUYERS:
            u, new = await _user(s, f"{slug(name)}@{SEED_DOMAIN}", name, UserRole.BUYER, city=city, lang=lang, password=password)
            buyers.append((u, city))
            out.users += new

        have = {(r.crop, r.market, r.report_date) for r in (await s.scalars(select(MarketReport).where(MarketReport.source == SAMPLE_SOURCE))).all()}
        for crop, (_, base) in CROPS.items():
            for ci, (city, (_, _, _, mandi)) in enumerate(CITIES.items()):
                for d in range(30):
                    day = today - timedelta(days=d)
                    if (crop, mandi, day) in have:
                        continue
                    wobble = ((d * 37 + ci * 11 + len(crop) * 7) % 21 - 10) * base // 200  # deterministic +-5 %
                    avg = base + wobble + ci * 50
                    s.add(MarketReport(crop=crop, location=city, market=mandi, min_price_paise=avg - 250, max_price_paise=avg + 350,
                                       average_price_paise=avg, report_date=day, source=SAMPLE_SOURCE, is_sample=True))
                    out.market_reports += 1

        plan = [("Tomato", 800, Grade.A, 0), ("Onion", 1500, Grade.B, 1), ("Potato", 2000, Grade.A, 2), ("Banana", 600, Grade.A, 3),
                ("Wheat", 5000, Grade.B, 0), ("Rice", 4000, Grade.A, 1), ("Tomato", 300, Grade.B, 3), ("Onion", 900, Grade.A, 2)]
        for crop, qty, grade, fi in plan:
            farmer, city = farmers[fi % len(farmers)]
            exists = await s.scalar(select(Listing.id).where(Listing.farmer_id == farmer.id, Listing.crop_name == crop,
                                                             Listing.quantity_kg == Decimal(qty)))
            if exists:
                continue
            category, base = CROPS[crop]
            state, lat, lon, _ = CITIES[city]
            s.add(Listing(farmer_id=farmer.id, crop_name=crop, crop_category=category, description="Sample listing (seed data)",
                          quantity_kg=Decimal(qty), reserved_kg=Decimal(0), base_price_paise=base + (50 if grade == Grade.A else 0),
                          ai_grade=grade, grade_confidence=0.9, status=ListingStatus.ACTIVE, location=city, state=state,
                          latitude=lat, longitude=lon, harvest_date=today - timedelta(days=2)))
            out.listings += 1

        wants = [("Tomato", 500, Grade.B, 0, 3200), ("Onion", 1000, Grade.B, 1, 2600), ("Rice", 2000, Grade.A, 2, 4200)]
        for crop, qty, grade, bi, cap in wants:
            buyer, city = buyers[bi]
            exists = await s.scalar(select(BuyerRequirement.id).where(BuyerRequirement.buyer_id == buyer.id, BuyerRequirement.crop_name == crop))
            if exists:
                continue
            s.add(BuyerRequirement(buyer_id=buyer.id, crop_name=crop, quantity_kg=Decimal(qty), min_grade=grade, location=city,
                                   max_price_paise=cap, notes="Sample requirement (seed data)", status=RequirementStatus.OPEN))
            out.requirements += 1
    return out


async def embed(settings: Settings) -> int:
    """Embeds the sample market reports with the configured provider (hash by default; Gemini when EMBEDDING_PROVIDER=gemini)."""
    from app.services.embedding import build_embedding_provider
    from app.services.market import MarketService
    total = 0
    async with get_sessionmaker()() as s:
        svc = MarketService(s, build_embedding_provider(settings))
        while (n := await svc.embed_pending(100)):
            total += n
    return total


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--password", help="password for the seeded farmer/buyer accounts (default: random, printed once)")
    ap.add_argument("--allow-production", action="store_true")
    args = ap.parse_args()
    settings = get_settings()
    if settings.is_production and not args.allow_production:
        raise SystemExit("refusing to seed a production environment (pass --allow-production if you really mean it)")
    password = args.password or secrets.token_urlsafe(12)
    res = await seed(get_sessionmaker(), password)
    embedded = await embed(settings)
    print(f"seeded: {res.users} users, {res.market_reports} market reports, {res.listings} listings, {res.requirements} requirements; embedded {embedded}")
    if res.users and not args.password:
        print(f"seed account password (shown once): {password}   accounts: *@{SEED_DOMAIN}")
    print("demo accounts need DEMO_MODE=true to be usable via POST /auth/demo")


if __name__ == "__main__":
    asyncio.run(main())
