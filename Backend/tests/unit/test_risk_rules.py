import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.agents.fraud_risk import rules as R
from app.agents.fraud_risk.summarizer import validate_summary
from app.core.config import get_settings
from app.models.enums import AnomalySeverity as S

ST = get_settings()
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
F, L = uuid.uuid4(), uuid.uuid4()


def lc(**kw):
    base = dict(listing_id=L, farmer_id=F, crop="Tomato", quantity_kg=Decimal(500), price_paise=3000, reference_paise=3000,
                edits_last_hour=0, now=NOW)
    return R.ListingCtx(**{**base, **kw})


def ids(signals):
    return [(s.rule_id, s.severity) for s in signals]


def test_normal_listing_raises_nothing():
    assert R.listing_rules(lc(), ST) == []
    assert R.listing_rules(lc(reference_paise=None, price_paise=1), ST) == []  # no market data => no price judgement


@pytest.mark.parametrize("price,expected", [(3000, []), (4400, []), (4500, [S.MEDIUM]), (1500, [S.MEDIUM]), (5400, [S.HIGH]), (600, [S.HIGH])])
def test_price_deviation_thresholds(price, expected):
    got = [s.severity for s in R.listing_rules(lc(price_paise=price), ST) if s.rule_id == "PRICE_DEVIATION"]
    assert got == expected


def test_dedupe_keys_are_stable_and_escalate_with_severity():
    a = R.listing_rules(lc(price_paise=1500), ST)[0]
    assert a.dedupe_key == R.listing_rules(lc(price_paise=1500), ST)[0].dedupe_key  # same situation => same key
    b = R.listing_rules(lc(price_paise=500), ST)[0]
    assert a.dedupe_key != b.dedupe_key  # an escalation creates a new flag
    assert a.subject_user_id == F and a.entity_type == "listing"


def test_large_lot_and_combo():
    assert ids(R.listing_rules(lc(quantity_kg=Decimal(60000)), ST)) == [("QUANTITY_PRICE_COMBINATION", S.LOW)]
    assert ids(R.listing_rules(lc(quantity_kg=Decimal(60000), price_paise=1800), ST)) == [("QUANTITY_PRICE_COMBINATION", S.MEDIUM)]


def test_edit_burst_duplicate_image_and_low_confidence():
    assert R.listing_rules(lc(edits_last_hour=4), ST) == []
    assert ids(R.listing_rules(lc(edits_last_hour=5), ST)) == [("LISTING_EDIT_BURST", S.MEDIUM)]
    d = R.listing_rules(lc(duplicate_image_listings=[uuid.uuid4()], duplicate_sha="ab" * 32), ST)
    assert ids(d) == [("DUPLICATE_IMAGE", S.MEDIUM)] and "ab" * 6 in d[0].dedupe_key
    g = R.listing_rules(lc(grading_result_id=uuid.uuid4(), grading_confidence=0.3), ST)
    assert ids(g) == [("LOW_AI_CONFIDENCE", S.LOW)]
    assert R.listing_rules(lc(grading_result_id=uuid.uuid4(), grading_confidence=0.9), ST) == []


def test_order_rules():
    o = R.OrderCtx(uuid.uuid4(), F, 20_000_000, 2.0, 1, NOW)
    assert ids(R.order_rules(o, ST)) == [("NEW_ACCOUNT_LARGE_ORDER", S.MEDIUM)]
    assert R.order_rules(R.OrderCtx(uuid.uuid4(), F, 20_000_000, 500.0, 1, NOW), ST) == []  # established account
    assert R.order_rules(R.OrderCtx(uuid.uuid4(), F, 1000, 2.0, 1, NOW), ST) == []  # small order
    assert ids(R.order_rules(R.OrderCtx(uuid.uuid4(), F, 1000, 500.0, 10, NOW), ST)) == [("ORDER_VELOCITY", S.MEDIUM)]


@pytest.mark.parametrize("n,expected", [(2, []), (3, [S.MEDIUM]), (4, [S.MEDIUM]), (5, [S.HIGH]), (9, [S.HIGH])])
def test_payment_failure_thresholds(n, expected):
    assert [s.severity for s in R.payment_rules(R.PaymentCtx(uuid.uuid4(), F, uuid.uuid4(), n, NOW), ST)] == expected


def test_wording_is_neutral_never_a_verdict():
    sigs = [*R.listing_rules(lc(price_paise=500, edits_last_hour=9, quantity_kg=Decimal(90000), duplicate_image_listings=[L],
                                grading_result_id=uuid.uuid4(), grading_confidence=0.1), ST),
            *R.order_rules(R.OrderCtx(uuid.uuid4(), F, 20_000_000, 1.0, 12, NOW), ST),
            *R.payment_rules(R.PaymentCtx(uuid.uuid4(), F, uuid.uuid4(), 8, NOW), ST)]
    assert len(sigs) >= 7
    for s in sigs:
        text = (s.reason + s.recommended_action).lower()
        assert not any(w in text for w in ("fraud", "scam", "criminal", "cheat", "guilty")), s.rule_id
        assert s.recommended_action and s.dedupe_key


SIGS = R.listing_rules(lc(price_paise=500), ST)


@pytest.mark.parametrize("text,ok", [
    ("The listed price is far below the market reference, worth a quick look.", True),
    (f"Price of Rs {SIGS[0].details['price_paise'] / 100} is far below the market reference of Rs 30.00.", True),
    ("This looks like fraud by the farmer.", False),
    ("A buyer lost Rs 99999 here, review now.", False),
    ("See http://evil.example for more detail on this flag.", False),
    ("short", False),
    (None, False),
])
def test_ai_summary_is_validated(text, ok):
    assert (validate_summary(text, SIGS) is not None) is ok
