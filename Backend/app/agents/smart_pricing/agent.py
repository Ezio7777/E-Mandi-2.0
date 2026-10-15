"""Smart Pricing Agent (LangGraph).

  load_context -> retrieve_market -> comparable_listings -> compute -> explain -> validate -> persist
                     (tools: market_reports_query, market_search[pgvector], comparable_listings)

Authority: `compute` (deterministic engine) sets every number. The LLM only writes the explanation, and is rejected
if it contains any number we did not supply. `validate` re-checks bounds before anything is persisted.
"""
import statistics
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.smart_pricing.explainer import PriceExplainer, allowed_numbers
from app.core.database import transactional
from app.core.logging import get_logger
from app.models.enums import Grade, NotificationType
from app.models.enums import ListingStatus as L
from app.models.listing import Listing
from app.models.pricing_result import PricingResult
from app.repositories.listing import ListingRepository
from app.repositories.market import MarketRepository
from app.services.audit import SYSTEM_ACTOR, AuditService
from app.services.embedding import EmbeddingProvider
from app.services.market import MarketService
from app.services.notification import NotificationService
from app.services.pricing import (
    WINDOW_DAYS,
    NoMarketDataError,
    PriceRecommendation,
    ReportPoint,
    compute_price,
    to_point,
    within_bounds,
)
from app.utils.crops import crop_or_title
from app.utils.money import paise_to_rupees
from app.utils.time import utcnow

log = get_logger(__name__)


class PricingValidationError(Exception):
    """Raised if a computed recommendation violates business invariants (indicates a bug, never persisted)."""


class PricingState(TypedDict, total=False):
    listing_id: uuid.UUID
    grading_result_id: uuid.UUID | None
    crop: str
    location: str
    grade: Grade | None
    quantity_kg: Decimal
    points: list[ReportPoint]
    retrieval: dict[str, Any]
    comparable: dict[str, Any]
    rec: PriceRecommendation
    explanation: str
    explanation_provider: str
    fallback_used: bool
    outcome: str  # priced | no_data | skipped
    result_id: uuid.UUID | None
    tool_calls: list[dict[str, Any]]


def _route(state: PricingState) -> str:
    return "stop" if state.get("outcome") in {"skipped", "no_data"} else "next"


class SmartPricingAgent:
    def __init__(self, session: AsyncSession, embedder: EmbeddingProvider, explainer: PriceExplainer) -> None:
        self.session, self.embedder, self.explainer = session, embedder, explainer
        self.listings, self.market = ListingRepository(session), MarketRepository(session)
        self.graph = self._build()

    def _build(self):
        g = StateGraph(PricingState)
        for name in ("load_context", "retrieve_market", "comparable_listings", "compute", "explain", "validate", "persist"):
            g.add_node(name, getattr(self, name))
        g.add_edge(START, "load_context")
        g.add_conditional_edges("load_context", _route, {"next": "retrieve_market", "stop": END})
        g.add_edge("retrieve_market", "comparable_listings")
        g.add_edge("comparable_listings", "compute")
        g.add_conditional_edges("compute", _route, {"next": "explain", "stop": END})
        g.add_edge("explain", "validate")
        g.add_edge("validate", "persist")
        g.add_edge("persist", END)
        return g.compile()

    async def run(self, listing_id: uuid.UUID, grading_result_id: uuid.UUID | None = None) -> PricingState:
        return await self.graph.ainvoke({"listing_id": listing_id, "grading_result_id": grading_result_id, "tool_calls": []})

    # ---------------- nodes ----------------
    async def load_context(self, s: PricingState) -> dict[str, Any]:
        l = await self.listings.get(s["listing_id"])
        if l is None or l.status in {L.ARCHIVED, L.SOLD}:
            return {"outcome": "skipped"}
        if s.get("grading_result_id"):
            done = await self.session.scalar(select(PricingResult.id).where(
                PricingResult.grading_result_id == s["grading_result_id"]).limit(1))
            if done:  # idempotent: this grading result was already priced
                return {"outcome": "skipped"}
        qty = l.available_kg if l.available_kg > 0 else l.quantity_kg
        return {"crop": crop_or_title(l.crop_name), "location": l.location, "grade": l.ai_grade, "quantity_kg": qty}

    async def retrieve_market(self, s: PricingState) -> dict[str, Any]:
        rows = await self.market.list_reports(crop=s["crop"], since=utcnow().date() - timedelta(days=WINDOW_DAYS), limit=500)
        calls = [*s["tool_calls"], {"tool": "market_reports_query", "ok": True, "n": len(rows)}]
        found = await MarketService(self.session, self.embedder).search(f"{s['crop']} price {s['location']}", 5, crop=s["crop"])
        calls.append({"tool": "market_search", "ok": True, "mode": found.mode, "n": len(found.hits)})
        return {"points": [to_point(r, s["location"]) for r in rows], "tool_calls": calls,
                "retrieval": {"mode": found.mode, "n": len(found.hits)}}

    async def comparable_listings(self, s: PricingState) -> dict[str, Any]:
        prices = list((await self.session.scalars(select(Listing.base_price_paise).where(
            func.lower(Listing.crop_name) == s["crop"].lower(), Listing.status == L.ACTIVE,
            Listing.id != s["listing_id"]))).all())
        comp = {"count": len(prices), "median_paise": int(statistics.median_low(prices)) if prices else None}
        return {"comparable": comp, "tool_calls": [*s["tool_calls"], {"tool": "comparable_listings", "ok": True, "n": len(prices)}]}

    async def compute(self, s: PricingState) -> dict[str, Any]:
        try:
            rec = compute_price(crop=s["crop"], grade=s["grade"], quantity_kg=s["quantity_kg"], reports=s["points"],
                                today=utcnow().date())
        except NoMarketDataError:
            return {"outcome": "no_data"}  # never fabricate a price
        return {"rec": rec}

    async def explain(self, s: PricingState) -> dict[str, Any]:
        rec, comp = s["rec"], s["comparable"]
        r = lambda p: f"{paise_to_rupees(p)}"  # noqa: E731
        facts: dict[str, Any] = {"crop": s["crop"], "location": s["location"], "grade": s["grade"].value if s["grade"] else "unknown",
                 "quantity_kg": str(s["quantity_kg"]), "suggested_price_per_kg": r(rec.suggested_paise),
                 "range_per_kg": [r(rec.range_min_paise), r(rec.range_max_paise)], "market_reference_per_kg": r(rec.reference_paise),
                 "trend": rec.trend, "scope": rec.scope, "data_points": rec.data_points,
                 "factors": [{"name": f.name, "effect_pct": f.effect_pct, "detail": f.detail} for f in rec.factors]}
        extra = []
        if comp["median_paise"]:
            facts["comparable_active_listings"] = {"count": comp["count"], "median_per_kg": r(comp["median_paise"])}
            extra.append(comp["median_paise"])
        allowed = allowed_numbers(rec, extra) | {Decimal(comp["count"])}
        ex = await self.explainer.explain(facts, allowed)
        calls = [*s["tool_calls"], {"tool": "llm_explain", "ok": ex.text is not None, "provider": ex.provider}]
        return {"explanation": ex.text or rec.explanation, "explanation_provider": ex.provider or "deterministic",
                "fallback_used": ex.fallback_used, "tool_calls": calls}

    async def validate(self, s: PricingState) -> dict[str, Any]:
        rec = s["rec"]
        if not (rec.range_min_paise <= rec.suggested_paise <= rec.range_max_paise and rec.suggested_paise > 0
                and within_bounds(rec.suggested_paise, rec.reference_paise)):
            raise PricingValidationError("recommendation violates business bounds")
        return {}

    async def persist(self, s: PricingState) -> dict[str, Any]:
        rec, comp = s["rec"], s["comparable"]
        factors = [{"name": f.name, "effectPct": f.effect_pct, "detail": f.detail} for f in rec.factors]
        if comp["median_paise"]:
            factors.append({"name": "comparable_listings", "effectPct": 0.0, "informational": True,
                            "detail": f"{comp['count']} active listing(s), median Rs {paise_to_rupees(comp['median_paise'])}/kg"})
        async with transactional(self.session):
            l = await self.listings.get_for_update(s["listing_id"])
            if l is None or l.status in {L.ARCHIVED, L.SOLD}:
                return {"outcome": "skipped"}
            res = PricingResult(
                listing_id=l.id, grading_result_id=s.get("grading_result_id"), suggested_paise=rec.suggested_paise,
                range_min_paise=rec.range_min_paise, range_max_paise=rec.range_max_paise, reference_paise=rec.reference_paise,
                trend=rec.trend, scope=rec.scope, data_points=rec.data_points, is_sample=rec.is_sample, source=rec.source,
                explanation=s["explanation"], explanation_provider=s["explanation_provider"],
                fallback_used=s["fallback_used"], factors=factors)
            self.session.add(res)
            await self.session.flush()
            prev = l.suggested_price_paise
            l.suggested_price_paise = rec.suggested_paise
            AuditService(self.session).record(
                action="pricing.completed", entity_type="listing", entity_id=l.id, actor=SYSTEM_ACTOR,
                metadata={"pricing_result_id": str(res.id), "explanation_provider": res.explanation_provider,
                          "scope": rec.scope, "trend": rec.trend, "retrieval": s.get("retrieval", {})},
                previous_state={"suggested_price_paise": prev}, new_state={"suggested_price_paise": rec.suggested_paise})
            NotificationService(self.session).add(
                l.farmer_id, NotificationType.SYSTEM, "Price suggestion ready",
                f"Suggested price for your {l.crop_name}: Rs {paise_to_rupees(rec.suggested_paise)}/kg "
                f"(range Rs {paise_to_rupees(rec.range_min_paise)}-{paise_to_rupees(rec.range_max_paise)}).",
                {"listing_id": str(l.id), "pricing_result_id": str(res.id), "kind": "pricing"})
        return {"outcome": "priced", "result_id": res.id}
