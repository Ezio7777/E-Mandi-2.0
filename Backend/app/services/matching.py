"""Deterministic buyer-matching engine. Hard gates (grade, price ceiling, stock, status) decide ELIGIBILITY; five
weighted factor scores decide RANKING. No LLM is involved in selecting or scoring inventory - the agent only
controls the multi-step search loop and persistence around this module.

score = 0.15*grade + 0.30*quantity + 0.20*location + 0.25*price + 0.10*availability      (each factor 0..1)
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.models.enums import Grade
from app.repositories.listing import grades_at_least
from app.utils.crops import normalize_text
from app.utils.geo import GeoPoint, canonical_city, haversine_km
from app.utils.money import fmt_kg, paise_to_rupees

WEIGHTS = {"grade": 0.15, "quantity": 0.30, "location": 0.20, "price": 0.25, "availability": 0.10}
WEIGHTS_VERSION = "v1"
LOCATION_DECAY_KM = 500.0
NEAR_KM = 50.0  # "matched" threshold for the location factor


@dataclass(frozen=True)
class Requirement:
    crop: str
    quantity_kg: Decimal
    min_grade: Grade
    location: str
    max_price_paise: int
    needed_by: date | None
    geo: GeoPoint | None


@dataclass(frozen=True)
class Candidate:
    listing_id: Any
    farmer_id: Any
    crop: str
    available_kg: Decimal
    price_paise: int
    grade: Grade | None
    location: str
    geo: GeoPoint | None
    harvest_date: date | None


@dataclass
class Scored:
    listing_id: Any
    farmer_id: Any
    score: float
    grade_score: float
    quantity_score: float
    location_score: float
    price_score: float
    availability_score: float
    distance_km: float | None
    available_kg: Decimal
    reasons: list[dict[str, Any]] = field(default_factory=list)
    breakdown: dict[str, Any] = field(default_factory=dict)
    search_step: int = 0
    price_paise: int = 0


def is_eligible(req: Requirement, c: Candidate) -> bool:
    """Hard gates: grade meets minimum, price within ceiling, stock available."""
    return bool(c.grade and c.grade in grades_at_least(req.min_grade) and c.price_paise <= req.max_price_paise
                and c.available_kg > 0)


def locate(req: Requirement, c: Candidate) -> tuple[float | None, bool]:
    """(distance_km or None if unknown, same_city)."""
    rc, cc = canonical_city(req.location), canonical_city(c.location)
    same = (rc is not None and rc == cc) or normalize_text(req.location) == normalize_text(c.location)
    if same:
        return 0.0, True
    if req.geo and c.geo:
        return round(haversine_km(req.geo, c.geo), 1), False
    return None, False


def in_scope(distance: float | None, same_city: bool, radius_km: int) -> bool:
    if radius_km < 0:
        return True  # anywhere
    if same_city:
        return True
    return radius_km > 0 and distance is not None and distance <= radius_km


def price_score(price: int, ceiling: int) -> float:
    ratio = price / ceiling
    return 1.0 if ratio <= 0.85 else round(1.0 - (ratio - 0.85) / 0.15 * 0.5, 4)  # 0.85 -> 1.0 ... 1.0 -> 0.5


def availability_score(req: Requirement, c: Candidate) -> float:
    full_stock = c.available_kg >= req.quantity_kg
    timely = not (req.needed_by and c.harvest_date and c.harvest_date > req.needed_by)
    return 1.0 if (full_stock and timely) else 0.4 if (not full_stock and not timely) else 0.7


def score_candidate(req: Requirement, c: Candidate, distance: float | None, same_city: bool) -> Scored:
    g = 1.0  # hard-gated: reaching here means the grade meets the minimum
    q = float(min(Decimal(1), c.available_kg / req.quantity_kg))
    loc = 1.0 if same_city else (max(0.1, 1 - distance / LOCATION_DECAY_KM) if distance is not None else 0.1)
    p = price_score(c.price_paise, req.max_price_paise)
    a = availability_score(req, c)
    total = round(WEIGHTS["grade"] * g + WEIGHTS["quantity"] * q + WEIGHTS["location"] * loc
                  + WEIGHTS["price"] * p + WEIGHTS["availability"] * a, 4)
    full = c.available_kg >= req.quantity_kg
    near = same_city or (distance is not None and distance <= NEAR_KM)
    rs = lambda x: f"Rs {paise_to_rupees(x)}"  # noqa: E731
    loc_detail = (f"Same city ({req.location})" if same_city else
                  f"About {distance:g} km away (straight-line)" if distance is not None else "Distance unknown (location not recognised)")
    reasons = [
        {"factor": "grade", "matched": True, "detail": f"Grade {c.grade.value if c.grade else '?'} meets the required minimum Grade {req.min_grade.value}"},
        {"factor": "quantity", "matched": full, "detail": f"{fmt_kg(c.available_kg)} kg available of {fmt_kg(req.quantity_kg)} kg requested ({round(q * 100)}% covered)"},
        {"factor": "location", "matched": near, "detail": loc_detail},
        {"factor": "price", "matched": True, "detail": f"{rs(c.price_paise)}/kg vs maximum {rs(req.max_price_paise)}/kg ({round(c.price_paise / req.max_price_paise * 100)}% of budget)"},
        {"factor": "availability", "matched": a == 1.0, "detail": ("Fully available now" if full else "Only partially available") +
                                                               ("" if not (req.needed_by and c.harvest_date and c.harvest_date > req.needed_by)
                                                                else f"; harvest {c.harvest_date} is after the needed date {req.needed_by}")},
    ]
    breakdown = {"weights_version": WEIGHTS_VERSION, "weights": WEIGHTS,
                 "requirement": {"crop": req.crop, "quantity_kg": str(req.quantity_kg), "min_grade": req.min_grade.value,
                                 "location": req.location, "max_price_paise": req.max_price_paise,
                                 "needed_by": req.needed_by.isoformat() if req.needed_by else None},
                 "listing": {"price_paise": c.price_paise, "available_kg": str(c.available_kg),
                             "grade": c.grade.value if c.grade else None, "location": c.location,
                             "harvest_date": c.harvest_date.isoformat() if c.harvest_date else None}}
    return Scored(c.listing_id, c.farmer_id, total, g, round(q, 4), round(loc, 4), p, a, distance, c.available_kg,
                  reasons, breakdown, price_paise=c.price_paise)


def rank(scored: list[Scored]) -> list[Scored]:
    """Deterministic order: score desc, then cheaper, then more stock, then listing id (stable tie-break)."""
    return sorted(scored, key=lambda s: (-s.score, s.price_paise, -s.available_kg, str(s.listing_id)))


def total_available(scored: list[Scored]) -> Decimal:
    return sum((s.available_kg for s in scored), Decimal(0))
