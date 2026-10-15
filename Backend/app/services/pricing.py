"""Deterministic pricing engine. The numbers here are AUTHORITATIVE: an agent/LLM may explain or adjust within
validated bounds (see clamp_price / within_bounds) but can never invent the final price.

suggested = reference x grade x quantity x trend   (all factors are explicit and returned for explainability)
reference = recency-weighted (7-day half-life) mean of recent market averages, local reports preferred.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.enums import Grade
from app.models.market_report import MarketReport
from app.repositories.market import MarketRepository
from app.schemas.pricing import PriceFactorOut, PricingOut
from app.utils.crops import crop_or_title, normalize_text
from app.utils.money import paise_to_rupees
from app.utils.time import utcnow

WINDOW_DAYS = 30
HALF_LIFE_DAYS = 7.0
GRADE_MULTIPLIER = {Grade.A: 1.10, Grade.B: 1.00, Grade.C: 0.88, Grade.D: 0.72}
TREND_THRESHOLD = 0.03
TREND_ADJUST = {"up": 1.015, "stable": 1.0, "down": 0.985}
MIN_FACTOR, MAX_FACTOR = 0.4, 2.0  # business bounds relative to the reference price
ROUND_TO_PAISE = 50
MIN_PRICE_PAISE = 50


class NoMarketDataError(AppError):
    status_code, code = 404, "no_market_data"
    message = "No recent market data is available for this crop"


@dataclass(frozen=True)
class ReportPoint:
    report_date: date
    average_paise: int
    min_paise: int
    max_paise: int
    location_match: bool
    is_sample: bool
    market: str


@dataclass(frozen=True)
class PriceFactor:
    name: str
    effect_pct: float
    detail: str


@dataclass(frozen=True)
class PriceRecommendation:
    suggested_paise: int
    range_min_paise: int
    range_max_paise: int
    reference_paise: int
    trend: Literal["up", "down", "stable"]
    scope: Literal["local", "national_fallback"]
    data_points: int
    is_sample: bool
    source: str
    explanation: str
    factors: list[PriceFactor] = field(default_factory=list)


def round_paise(x: float) -> int:
    return max(MIN_PRICE_PAISE, round(x / ROUND_TO_PAISE) * ROUND_TO_PAISE)


def clamp_price(candidate_paise: int, reference_paise: int) -> int:
    lo, hi = round_paise(reference_paise * MIN_FACTOR), round_paise(reference_paise * MAX_FACTOR)
    return min(max(candidate_paise, lo), hi)


def within_bounds(candidate_paise: int, reference_paise: int) -> bool:
    return reference_paise * MIN_FACTOR <= candidate_paise <= reference_paise * MAX_FACTOR


def _quantity_multiplier(q: Decimal) -> tuple[float, str]:
    if q >= 5000:
        return 0.96, "very large lot (>=5000 kg): volume discount"
    if q >= 1000:
        return 0.98, "large lot (>=1000 kg): small volume discount"
    if q <= 50:
        return 1.02, "small lot (<=50 kg): small retail premium"
    return 1.0, "standard lot size"


def compute_price(*, crop: str, grade: Grade | None, quantity_kg: Decimal, reports: list[ReportPoint],
                  today: date) -> PriceRecommendation:
    recent = [r for r in reports if -1 <= (today - r.report_date).days <= WINDOW_DAYS]
    if not recent:
        raise NoMarketDataError(f"No market data in the last {WINDOW_DAYS} days for {crop}")
    local = [r for r in recent if r.location_match]
    scope: Literal["local", "national_fallback"] = "local" if local else "national_fallback"
    pts = local or recent

    def age(r: ReportPoint) -> int:
        return max(0, (today - r.report_date).days)

    weights = [0.5 ** (age(r) / HALF_LIFE_DAYS) for r in pts]
    reference = round(sum(w * r.average_paise for w, r in zip(weights, pts, strict=True)) / sum(weights))

    last7 = [r.average_paise for r in pts if age(r) <= 7]
    prior = [r.average_paise for r in pts if 7 < age(r) <= 14]
    trend: Literal["up", "down", "stable"] = "stable"
    trend_detail = "not enough history to detect a trend"
    if last7 and prior:
        change = (sum(last7) / len(last7)) / (sum(prior) / len(prior)) - 1
        trend = "up" if change >= TREND_THRESHOLD else "down" if change <= -TREND_THRESHOLD else "stable"
        trend_detail = f"last 7 days vs previous 7 days: {change * 100:+.1f}%"

    gm = GRADE_MULTIPLIER.get(grade, 1.0) if grade else 1.0
    qm, q_detail = _quantity_multiplier(quantity_kg)
    tm = TREND_ADJUST[trend]
    suggested = clamp_price(round_paise(reference * gm * qm * tm), reference)

    vol = sum((r.max_paise - r.min_paise) / (2 * r.average_paise) for r in pts) / len(pts)
    spread = min(max(vol, 0.05), 0.20) + (0.05 if scope == "national_fallback" or len(pts) < 3 else 0.0)
    rmin, rmax = round_paise(suggested * (1 - spread)), round_paise(suggested * (1 + spread))
    rmin, rmax = min(rmin, suggested), max(rmax, suggested)

    latest = max(pts, key=lambda r: r.report_date)
    all_sample = all(r.is_sample for r in pts)
    source = (f"{'Sample reference data' if all_sample else 'Market reports'} - {len(pts)} report(s), "
              f"latest {latest.report_date.isoformat()} at {latest.market}" + ("" if scope == "local" else " (other locations)"))
    factors = [
        PriceFactor("market_reference", 0.0, f"recency-weighted average of {len(pts)} {scope.replace('_', ' ')} report(s)"),
        PriceFactor("grade", round((gm - 1) * 100, 1), f"grade {grade.value if grade else 'unknown'} multiplier x{gm:.2f}"),
        PriceFactor("quantity", round((qm - 1) * 100, 1), q_detail),
        PriceFactor("trend", round((tm - 1) * 100, 1), trend_detail),
    ]
    explanation = (
        f"Reference market price is about Rs {paise_to_rupees(reference)}/kg for {crop}. "
        f"Adjusted for grade (x{gm:.2f}), lot size ({q_detail}) and the {trend} price trend, "
        f"the suggested price is Rs {paise_to_rupees(suggested)}/kg "
        f"(range Rs {paise_to_rupees(rmin)} to Rs {paise_to_rupees(rmax)}).")
    return PriceRecommendation(suggested, rmin, rmax, reference, trend, scope, len(pts), all_sample, source,
                               explanation, factors)


def to_point(r: MarketReport, location: str | None) -> ReportPoint:
    match = bool(location) and normalize_text(r.location) == normalize_text(location or "")
    return ReportPoint(r.report_date, r.average_price_paise, r.min_price_paise, r.max_price_paise, match, r.is_sample, r.market)


def to_out(rec: PriceRecommendation) -> PricingOut:
    return PricingOut(
        suggested=paise_to_rupees(rec.suggested_paise), range_min=paise_to_rupees(rec.range_min_paise),
        range_max=paise_to_rupees(rec.range_max_paise), reference_price=paise_to_rupees(rec.reference_paise),
        trend=rec.trend, explanation=rec.explanation, source=rec.source, scope=rec.scope,
        data_points=rec.data_points, is_sample=rec.is_sample,
        factors=[PriceFactorOut(name=f.name, effect_pct=f.effect_pct, detail=f.detail) for f in rec.factors])


class PricingService:
    def __init__(self, session: AsyncSession) -> None:
        self.market = MarketRepository(session)

    async def recommend(self, *, crop: str, location: str | None, grade: Grade | None, quantity_kg: Decimal,
                        today: date | None = None) -> PriceRecommendation:
        from datetime import timedelta
        today = today or utcnow().date()
        canon = crop_or_title(crop)
        rows = await self.market.list_reports(crop=canon, since=today - timedelta(days=WINDOW_DAYS), limit=500)
        return compute_price(crop=canon, grade=grade, quantity_kg=quantity_kg,
                             reports=[to_point(r, location) for r in rows], today=today)
