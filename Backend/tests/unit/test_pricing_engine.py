import random
from datetime import date, timedelta
from decimal import Decimal

import pytest
from app.models.enums import Grade
from app.services.pricing import (
    MIN_PRICE_PAISE,
    NoMarketDataError,
    ReportPoint,
    clamp_price,
    compute_price,
    round_paise,
    to_out,
    within_bounds,
)

TODAY = date(2026, 9, 30)


def pt(days_ago, avg=3000, spread=500, local=True, sample=True, market="Yeshwanthpur APMC"):
    return ReportPoint(TODAY - timedelta(days=days_ago), avg, avg - spread, avg + spread, local, sample, market)


def calc(reports, grade=Grade.B, qty=200, **kw):
    return compute_price(crop="Tomato", grade=grade, quantity_kg=Decimal(qty), reports=reports, today=TODAY, **kw)


def test_reference_is_recency_weighted():
    r = calc([pt(0, 4000), pt(28, 2000)])
    assert 3600 < r.reference_paise < 4000  # recent report dominates
    flat = calc([pt(1, 3000), pt(2, 3000), pt(3, 3000)])
    assert flat.reference_paise == 3000


@pytest.mark.parametrize(("grade", "mult"), [(Grade.A, 1.10), (Grade.B, 1.0), (Grade.C, 0.88), (Grade.D, 0.72), (None, 1.0)])
def test_grade_multiplier(grade, mult):
    reports = [pt(d, 3000) for d in (1, 2, 3, 4)]
    r = calc(reports, grade=grade)
    assert abs(r.suggested_paise - round_paise(3000 * mult)) <= 50
    assert r.suggested_paise <= calc(reports, grade=Grade.A).suggested_paise


def test_grade_ordering_is_monotonic():
    reports = [pt(d, 3000) for d in (1, 2, 3)]
    prices = [calc(reports, grade=g).suggested_paise for g in (Grade.A, Grade.B, Grade.C, Grade.D)]
    assert prices == sorted(prices, reverse=True) and len(set(prices)) == 4


def test_quantity_adjustment():
    reports = [pt(d, 10000) for d in (1, 2, 3)]
    small, mid, big, huge = (calc(reports, qty=q).suggested_paise for q in (20, 200, 2000, 8000))
    assert small > mid > big > huge


def test_trend_detection():
    up = calc([pt(1, 3300), pt(2, 3300), pt(9, 3000), pt(10, 3000)])
    down = calc([pt(1, 2700), pt(2, 2700), pt(9, 3000), pt(10, 3000)])
    flat = calc([pt(1, 3010), pt(9, 3000)])
    assert (up.trend, down.trend, flat.trend) == ("up", "down", "stable")
    assert calc([pt(1, 3000)]).trend == "stable"  # not enough history
    assert up.suggested_paise > round_paise(up.reference_paise) - 1


def test_range_contains_suggested_and_spread_has_floor():
    r = calc([pt(d, 3000, spread=0) for d in (1, 2, 3)])  # zero volatility
    assert r.range_min_paise < r.suggested_paise < r.range_max_paise
    assert r.range_max_paise / r.suggested_paise >= 1.04  # at least ~5% spread


def test_sparse_or_national_data_widens_range_and_flags_scope():
    local = calc([pt(d, 3000, spread=100) for d in (1, 2, 3)])
    fallback = calc([pt(d, 3000, spread=100, local=False) for d in (1, 2, 3)])
    assert local.scope == "local" and fallback.scope == "national_fallback"
    assert fallback.range_max_paise - fallback.range_min_paise > local.range_max_paise - local.range_min_paise
    assert "other locations" in fallback.source


def test_local_reports_preferred_over_national():
    r = calc([pt(1, 5000, local=True), pt(1, 1000, local=False)])
    assert r.scope == "local" and r.reference_paise == 5000 and r.data_points == 1


def test_no_market_data_never_fabricates_a_price():
    with pytest.raises(NoMarketDataError):
        calc([])
    with pytest.raises(NoMarketDataError):
        calc([pt(45, 3000)])  # stale (>30 days)


def test_sample_flag_and_source_text():
    assert calc([pt(1)]).is_sample and "Sample reference data" in calc([pt(1)]).source
    live = calc([pt(1, sample=False)])
    assert not live.is_sample and live.source.startswith("Market reports")


def test_extreme_values():
    tiny = calc([pt(1, 60, spread=10)])
    assert tiny.suggested_paise >= MIN_PRICE_PAISE and tiny.range_min_paise >= MIN_PRICE_PAISE
    big = calc([pt(1, 9_000_000)], qty=1_000_000)
    assert big.suggested_paise > 0 and big.range_min_paise <= big.suggested_paise <= big.range_max_paise
    single = calc([pt(0, 3000)], qty=Decimal("0.001"))
    assert single.suggested_paise > 0


def test_bounds_helpers():
    assert within_bounds(3000, 3000) and not within_bounds(100, 3000) and not within_bounds(10_000, 3000)
    assert clamp_price(100, 3000) == round_paise(1200) and clamp_price(99999, 3000) == round_paise(6000)
    assert clamp_price(3100, 3000) == 3100


def test_invariants_hold_for_random_inputs():
    rnd = random.Random(42)
    for _ in range(300):
        pts = [pt(rnd.randint(0, 29), rnd.randint(100, 500_000), spread=0, local=rnd.random() < .6) for _ in range(rnd.randint(1, 12))]
        pts = [ReportPoint(p.report_date, p.average_paise, max(1, p.average_paise - rnd.randint(0, p.average_paise - 1)),
                           p.average_paise + rnd.randint(0, 100_000), p.location_match, True, "m") for p in pts]
        r = calc(pts, grade=rnd.choice([*Grade, None]), qty=rnd.choice([1, 60, 1500, 9000]))
        assert MIN_PRICE_PAISE <= r.range_min_paise <= r.suggested_paise <= r.range_max_paise
        assert within_bounds(r.suggested_paise, r.reference_paise) or r.suggested_paise == MIN_PRICE_PAISE
        assert r.suggested_paise % 50 == 0 and r.trend in {"up", "down", "stable"} and r.explanation and r.factors


def test_output_contract_is_camel_case():
    d = to_out(calc([pt(1), pt(2)])).model_dump(by_alias=True, mode="json")
    for k in ("suggested", "rangeMin", "rangeMax", "referencePrice", "trend", "explanation", "source"):
        assert k in d, k
    assert isinstance(d["suggested"], float) and d["factors"][0].keys() >= {"name", "effectPct", "detail"}
