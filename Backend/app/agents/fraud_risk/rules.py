"""Deterministic risk rules. PURE functions: context in -> signals out (no I/O, no randomness, no LLM), so every flag is
reproducible and explainable. A signal means FLAGGED_FOR_REVIEW (a human looks); it is never a fraud verdict.
Wording is deliberately neutral ("may", "unusual") and each signal carries the recommended review action."""
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.config import Settings
from app.models.enums import AnomalySeverity as S
from app.utils.money import fmt_kg, paise_to_rupees


@dataclass(frozen=True)
class Signal:
    rule_id: str
    severity: S
    reason: str
    recommended_action: str
    entity_type: str
    entity_id: str
    dedupe_key: str
    details: dict[str, Any] = field(default_factory=dict)
    subject_user_id: uuid.UUID | None = None  # the account a human may want to look at (never auto-actioned)


@dataclass
class ListingCtx:
    listing_id: uuid.UUID
    farmer_id: uuid.UUID
    crop: str
    quantity_kg: Any  # Decimal
    price_paise: int
    reference_paise: int | None
    edits_last_hour: int
    now: datetime
    duplicate_image_listings: list[uuid.UUID] = field(default_factory=list)  # other farmers' listings sharing an image hash
    duplicate_sha: str | None = None
    grading_result_id: uuid.UUID | None = None
    grading_confidence: float | None = None
    grading_requires_review: bool = False


@dataclass
class OrderCtx:
    order_id: uuid.UUID
    buyer_id: uuid.UUID
    total_paise: int
    buyer_age_hours: float
    buyer_orders_last_hour: int
    now: datetime


@dataclass
class PaymentCtx:
    payment_id: uuid.UUID
    payer_id: uuid.UUID
    order_id: uuid.UUID
    failures_24h: int
    now: datetime


def _hour(now: datetime) -> str:
    return now.strftime("%Y%m%d%H")


def listing_rules(c: ListingCtx, s: Settings) -> list[Signal]:
    out: list[Signal] = []
    eid, kg = str(c.listing_id), c.quantity_kg
    dev_pct: float | None = None
    if c.reference_paise:
        dev_pct = round((c.price_paise / c.reference_paise - 1) * 100, 1)
        a = abs(dev_pct)
        sev = S.HIGH if a >= s.RISK_PRICE_DEVIATION_HIGH_PCT else S.MEDIUM if a >= s.RISK_PRICE_DEVIATION_MEDIUM_PCT else None
        if sev:
            direction = "above" if dev_pct > 0 else "below"
            out.append(Signal(
                "PRICE_DEVIATION", sev,
                f"Listed price Rs {paise_to_rupees(c.price_paise)}/kg for {c.crop} is {a:.0f}% {direction} the market reference "
                f"of Rs {paise_to_rupees(c.reference_paise)}/kg. This may be a data-entry slip or an unusual offer.",
                "Review the listing price with the farmer; no action is needed if the price is intentional.",
                "listing", eid, f"PRICE_DEVIATION:{eid}:{sev.value}:{'up' if dev_pct > 0 else 'down'}",
                {"price_paise": c.price_paise, "reference_paise": c.reference_paise, "deviation_pct": dev_pct}, c.farmer_id))
    if kg >= s.RISK_LARGE_LOT_KG:
        combo = dev_pct is not None and dev_pct <= -(s.RISK_PRICE_DEVIATION_MEDIUM_PCT // 2)
        out.append(Signal(
            "QUANTITY_PRICE_COMBINATION", S.MEDIUM if combo else S.LOW,
            f"Unusually large lot ({fmt_kg(kg)} kg of {c.crop})" + (f" priced {abs(dev_pct):.0f}% below market." if combo else "."),  # type: ignore[arg-type]
            "Confirm the quantity and price are correct before the lot is shown to buyers.",
            "listing", eid, f"QUANTITY_PRICE_COMBINATION:{eid}:{'combo' if combo else 'size'}",
            {"quantity_kg": str(kg), "deviation_pct": dev_pct}, c.farmer_id))
    if c.edits_last_hour >= s.RISK_LISTING_EDITS_PER_HOUR:
        out.append(Signal(
            "LISTING_EDIT_BURST", S.MEDIUM,
            f"This listing was edited {c.edits_last_hour} times in the last hour, which is more than usual.",
            "Check the edit history in the audit log for changes made after buyers showed interest.",
            "listing", eid, f"LISTING_EDIT_BURST:{eid}:{_hour(c.now)}", {"edits_last_hour": c.edits_last_hour}, c.farmer_id))
    if c.duplicate_image_listings:
        n = len(c.duplicate_image_listings)
        out.append(Signal(
            "DUPLICATE_IMAGE", S.MEDIUM,
            f"An image on this listing is identical to images on {n} other listing(s) from different accounts. "
            "This may be a reused photo or a shared stock image.",
            "Compare the listings and ask the farmer for a fresh photo of the actual produce if needed.",
            "listing", eid, f"DUPLICATE_IMAGE:{eid}:{(c.duplicate_sha or '')[:12]}",
            {"other_listing_ids": [str(x) for x in c.duplicate_image_listings[:10]], "image_sha256_prefix": (c.duplicate_sha or "")[:12]}, c.farmer_id))
    if c.grading_confidence is not None and c.grading_result_id and (c.grading_requires_review or c.grading_confidence < s.RISK_LOW_CONFIDENCE_FLAG):
        out.append(Signal(
            "LOW_AI_CONFIDENCE", S.LOW,
            f"The AI grade for this listing has low confidence ({c.grading_confidence:.2f}).",
            "Use the grading review queue to confirm, override or reject the grade.",
            "listing", eid, f"LOW_AI_CONFIDENCE:{c.grading_result_id}", {"confidence": c.grading_confidence}, c.farmer_id))
    return out


def order_rules(c: OrderCtx, s: Settings) -> list[Signal]:
    out: list[Signal] = []
    eid = str(c.order_id)
    if c.buyer_age_hours < s.RISK_NEW_ACCOUNT_HOURS and c.total_paise >= s.RISK_NEW_ACCOUNT_ORDER_PAISE:
        out.append(Signal(
            "NEW_ACCOUNT_LARGE_ORDER", S.MEDIUM,
            f"A buyer account created {c.buyer_age_hours:.0f} hour(s) ago placed an order of Rs {paise_to_rupees(c.total_paise)}, "
            "which is unusual for a new account.",
            "Review the order and account before the farmer ships; contact the buyer if anything looks off.",
            "order", eid, f"NEW_ACCOUNT_LARGE_ORDER:{eid}", {"total_paise": c.total_paise, "account_age_hours": round(c.buyer_age_hours, 1)}, c.buyer_id))
    if c.buyer_orders_last_hour >= s.RISK_ORDERS_PER_HOUR:
        out.append(Signal(
            "ORDER_VELOCITY", S.MEDIUM,
            f"This buyer created {c.buyer_orders_last_hour} orders in the last hour, which is more than usual.",
            "Check whether the orders are legitimate bulk buying or repeated test/abuse activity.",
            "order", eid, f"ORDER_VELOCITY:{c.buyer_id}:{_hour(c.now)}", {"orders_last_hour": c.buyer_orders_last_hour}, c.buyer_id))
    return out


def payment_rules(c: PaymentCtx, s: Settings) -> list[Signal]:
    n, t = c.failures_24h, s.RISK_PAYMENT_FAILURES_24H
    if n < t:
        return []
    sev = S.HIGH if n >= t + 2 else S.MEDIUM
    return [Signal(
        "REPEATED_PAYMENT_FAILURES", sev,
        f"{n} payment attempts by this account failed in the last 24 hours. This is often a card or bank issue rather than misuse.",
        "Review the failure reasons; reach out to the buyer before taking any account action.",
        "payment", str(c.payment_id), f"REPEATED_PAYMENT_FAILURES:{c.payer_id}:{c.now.strftime('%Y%m%d')}:{sev.value}",
        {"failures_24h": n, "order_id": str(c.order_id)}, c.payer_id)]
