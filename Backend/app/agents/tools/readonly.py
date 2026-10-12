"""Controlled, read-only tools for the Voice Assistant Agent.

Safety model (the agent has NO other database access):
  * a fixed whitelist of tools; anything else raises ToolNotAllowed
  * per-tool role permissions are enforced HERE (not only in the graph), so a bug upstream cannot widen access
  * every tool returns plain facts (no ORM objects, no other user's data, no farmer identity on public listings)
  * every call is timed, bounded (VOICE_TOOL_TIMEOUT_SECONDS) and recorded in `calls` for the execution record
  * tools only SELECT. Mutating actions live in tools/action_requests.py and are never reachable from voice.
"""
import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ForbiddenError
from app.models.enums import ListingStatus, UserRole
from app.repositories.listing import ListingFilters, ListingRepository
from app.repositories.market import MarketRepository
from app.services.embedding import EmbeddingProvider
from app.services.market import MarketService
from app.services.pricing import NoMarketDataError, PricingService
from app.utils.crops import crop_or_title
from app.utils.time import utcnow


class ToolNotAllowed(Exception):
    pass


ALL_ROLES = frozenset({UserRole.FARMER, UserRole.BUYER, UserRole.ADMIN})
TOOL_ROLES: dict[str, frozenset[UserRole]] = {
    "market_search": ALL_ROLES,
    "historical_market_search": ALL_ROLES,
    "price_advice": frozenset({UserRole.FARMER, UserRole.ADMIN}),
    "listing_search": ALL_ROLES,
    "farmer_inventory_lookup": frozenset({UserRole.FARMER}),
}


@dataclass(frozen=True)
class ReportFact:
    crop: str
    location: str
    market: str
    report_date: str
    average_paise: int
    min_paise: int
    max_paise: int
    is_sample: bool


@dataclass(frozen=True)
class ListingFact:
    crop: str
    grade: str | None
    available_kg: Decimal
    price_paise: int
    location: str


@dataclass(frozen=True)
class PriceAdviceFact:
    crop: str
    suggested_paise: int
    range_min_paise: int
    range_max_paise: int
    reference_paise: int
    trend: str
    scope: str
    data_points: int
    is_sample: bool
    source: str


@dataclass
class ToolBelt:
    session: AsyncSession
    embedder: EmbeddingProvider
    settings: Settings
    user_id: uuid.UUID
    role: UserRole
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def _run(self, name: str, coro: Callable[[], Awaitable[Any]]) -> Any:
        if name not in TOOL_ROLES:
            raise ToolNotAllowed(name)
        if self.role not in TOOL_ROLES[name]:
            self.calls.append({"tool": name, "ok": False, "rows": 0, "ms": 0, "error": "forbidden"})
            raise ForbiddenError("This question is not available for your account type")
        t0, rows, ok = time.perf_counter(), 0, True
        try:
            res = await asyncio.wait_for(coro(), self.settings.VOICE_TOOL_TIMEOUT_SECONDS)
            rows = len(res) if isinstance(res, list) else (0 if res is None else 1)
            return res
        except BaseException:
            ok = False
            raise
        finally:
            self.calls.append({"tool": name, "ok": ok, "rows": rows, "ms": int((time.perf_counter() - t0) * 1000)})

    @staticmethod
    def _fact(r: Any) -> ReportFact:
        return ReportFact(r.crop, r.location, r.market, r.report_date.isoformat(), r.average_price_paise,
                          r.min_price_paise, r.max_price_paise, r.is_sample)

    async def market_search(self, query: str, crop: str | None, location: str | None) -> list[ReportFact]:
        """Semantic (pgvector) retrieval over market reports with a deterministic keyword fallback. Prefers the asked
        city; if the city has no data, retries without it so the answer can say so explicitly."""
        async def go() -> list[ReportFact]:
            svc = MarketService(self.session, self.embedder)
            out = await svc.search(query, 5, crop=crop, location=location)
            if not out.hits and location:
                out = await svc.search(query, 5, crop=crop, location=None)
            hits = [h.report for h in out.hits]
            return [ReportFact(h.crop, h.location, h.market, h.report_date.isoformat(), int(h.average_price * 100),
                               int(h.min_price * 100), int(h.max_price * 100), h.is_sample) for h in hits]
        return await self._run("market_search", go)

    async def historical_market_search(self, crop: str, location: str | None, days: int) -> list[ReportFact]:
        async def go() -> list[ReportFact]:
            repo = MarketRepository(self.session)
            since = utcnow().date() - timedelta(days=days)
            rows = await repo.list_reports(crop=crop_or_title(crop), location=location, since=since, limit=200)
            if not rows and location:
                rows = await repo.list_reports(crop=crop_or_title(crop), since=since, limit=200)
            return [self._fact(r) for r in rows]
        return await self._run("historical_market_search", go)

    async def price_advice(self, crop: str, location: str | None, quantity_kg: Decimal) -> PriceAdviceFact | None:
        async def go() -> PriceAdviceFact | None:
            try:
                rec = await PricingService(self.session).recommend(crop=crop, location=location, grade=None, quantity_kg=quantity_kg)
            except NoMarketDataError:
                return None
            return PriceAdviceFact(crop_or_title(crop), rec.suggested_paise, rec.range_min_paise, rec.range_max_paise,
                                   rec.reference_paise, rec.trend, rec.scope, rec.data_points, rec.is_sample, rec.source)
        return await self._run("price_advice", go)

    async def listing_search(self, crop: str | None, location: str | None) -> list[ListingFact]:
        """PUBLIC facts only: ACTIVE listings with stock. No farmer id/name/contact is ever returned."""
        async def go() -> list[ListingFact]:
            f = ListingFilters(statuses=[ListingStatus.ACTIVE], crop=crop_or_title(crop) if crop else None, location=location)
            rows = await ListingRepository(self.session).search(f, None, 20)
            return [ListingFact(l.crop_name, l.ai_grade.value if l.ai_grade else None, l.quantity_kg - l.reserved_kg,
                                l.base_price_paise, l.location or "") for l in rows if l.quantity_kg - l.reserved_kg > 0][:10]
        return await self._run("listing_search", go)

    async def farmer_inventory_lookup(self) -> list[ListingFact]:
        """The CALLER's own listings only: farmer_id comes from the authenticated user, never from the utterance."""
        async def go() -> list[ListingFact]:
            f = ListingFilters(statuses=[ListingStatus.ACTIVE], farmer_id=self.user_id)
            rows = await ListingRepository(self.session).search(f, None, 20)
            return [ListingFact(l.crop_name, l.ai_grade.value if l.ai_grade else None, l.quantity_kg - l.reserved_kg,
                                l.base_price_paise, l.location or "") for l in rows][:10]
        return await self._run("farmer_inventory_lookup", go)
