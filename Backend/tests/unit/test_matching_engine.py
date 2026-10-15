import random
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from app.models.enums import Grade
from app.services.matching import (
    WEIGHTS,
    Candidate,
    Requirement,
    in_scope,
    is_eligible,
    locate,
    price_score,
    rank,
    score_candidate,
    total_available,
)
from app.utils.geo import canonical_city, haversine_km, resolve_point

BLR = resolve_point("Bangalore")
REQ = Requirement("Tomato", Decimal(500), Grade.A, "Bangalore", 3500, None, BLR)  # the spec's example requirement


def cand(qty=800, price=2850, grade=Grade.A, loc="Bengaluru", harvest=None, lid=None):
    return Candidate(lid or uuid.uuid4(), uuid.uuid4(), "Tomato", Decimal(qty), price, grade, loc, resolve_point(loc), harvest)


def score(c, req=REQ):
    d, same = locate(req, c)
    return score_candidate(req, c, d, same)


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_spec_example_scores_perfect_and_explains_each_factor():
    s = score(cand())
    assert s.score == 1.0 and (s.grade_score, s.quantity_score, s.location_score, s.price_score, s.availability_score) == (1, 1, 1, 1, 1)
    assert [r["factor"] for r in s.reasons] == ["grade", "quantity", "location", "price", "availability"]
    assert all(r["matched"] and r["detail"] for r in s.reasons)
    assert "Same city" in s.reasons[2]["detail"] and "Rs 28.50/kg vs maximum Rs 35.00/kg" in s.reasons[3]["detail"]


@pytest.mark.parametrize(("price", "expected"), [(2975, 1.0), (1000, 1.0), (3500, 0.5), (3237.5, 0.75)])
def test_price_score_curve(price, expected):
    assert abs(price_score(price, 3500) - expected) < 0.01


def test_partial_stock_lowers_quantity_and_availability():
    s = score(cand(qty=250))
    assert s.quantity_score == 0.5 and s.availability_score == 0.7
    assert s.reasons[1]["matched"] is False and "50% covered" in s.reasons[1]["detail"]


def test_late_harvest_reduces_availability():
    req = Requirement("Tomato", Decimal(500), Grade.A, "Bangalore", 3500, date.today() + timedelta(days=2), BLR)
    assert score(cand(harvest=date.today() + timedelta(days=5)), req).availability_score == 0.7
    assert score(cand(harvest=date.today() + timedelta(days=1)), req).availability_score == 1.0
    assert score(cand(qty=100, harvest=date.today() + timedelta(days=5)), req).availability_score == 0.4


@pytest.mark.parametrize(("kw", "ok"), [
    ({}, True), ({"grade": Grade.B}, False), ({"grade": None}, False), ({"price": 3501}, False), ({"price": 3500}, True),
    ({"qty": 0}, False)])
def test_hard_gates(kw, ok):
    assert is_eligible(REQ, cand(**kw)) is ok


def test_lower_min_grade_admits_lower_grades():
    req = Requirement("Tomato", Decimal(100), Grade.C, "Bangalore", 3500, None, BLR)
    assert is_eligible(req, cand(grade=Grade.C)) and not is_eligible(req, cand(grade=Grade.D))


def test_location_scope_and_distance():
    mys = cand(loc="Mysore")
    d, same = locate(REQ, mys)
    assert not same and 100 < d < 160  # Bengaluru-Mysuru straight line ~128 km
    assert locate(REQ, cand(loc="Yeshwanthpur, Bengaluru")) == (0.0, True)
    assert locate(REQ, cand(loc="Xyzville")) == (None, False)
    assert [in_scope(d, same, r) for r in (0, 50, 150, -1)] == [False, False, True, True]
    assert in_scope(0.0, True, 0) and in_scope(None, False, -1) and not in_scope(None, False, 400)


def test_location_score_decays_with_distance_and_unknown_is_weak():
    near, mid, far = score(cand(loc="Kolar")), score(cand(loc="Hubballi")), score(cand(loc="Delhi"))
    assert 1.0 > near.location_score > mid.location_score > far.location_score >= 0.1
    unk = score(cand(loc="Xyzville"))
    assert unk.location_score == 0.1 and "Distance unknown" in unk.reasons[2]["detail"]


def test_ranking_orders_by_score_then_price_then_stock_then_id():
    a, b, c = cand(loc="Bengaluru"), cand(loc="Mysore"), cand(loc="Delhi")
    order = [s.listing_id for s in rank([score(c), score(a), score(b)])]
    assert order == [a.listing_id, b.listing_id, c.listing_id]
    t1, t2 = cand(price=2500, lid=uuid.UUID(int=2)), cand(price=2600, lid=uuid.UUID(int=1))  # both price_score 1.0
    assert [s.listing_id for s in rank([score(t2), score(t1)])] == [t1.listing_id, t2.listing_id]  # cheaper wins the tie
    e1, e2 = cand(qty=900, lid=uuid.UUID(int=9)), cand(qty=800, lid=uuid.UUID(int=1))  # equal score+price, more stock first
    assert rank([score(e2), score(e1)])[0].listing_id == e1.listing_id
    i1, i2 = cand(lid=uuid.UUID(int=1)), cand(lid=uuid.UUID(int=2))  # full tie -> id
    assert rank([score(i2), score(i1)])[0].listing_id == i1.listing_id


def test_ranking_is_order_independent():
    cs = [cand(qty=random.randint(50, 900), price=random.randint(1000, 3500), loc=random.choice(["Bengaluru", "Kolar", "Mysore", "Pune", "Xyz"]))
          for _ in range(30)]
    scored = [score(c) for c in cs]
    base = [s.listing_id for s in rank(scored)]
    for seed in range(5):
        shuffled = scored[:]
        random.Random(seed).shuffle(shuffled)
        assert [s.listing_id for s in rank(shuffled)] == base
    assert all(0.0 <= s.score <= 1.0 for s in scored)


def test_breakdown_reproduces_score():
    s = score(cand(qty=300, price=3000, loc="Kolar"))
    b = s.breakdown
    req = Requirement(b["requirement"]["crop"], Decimal(b["requirement"]["quantity_kg"]), Grade(b["requirement"]["min_grade"]),
                      b["requirement"]["location"], b["requirement"]["max_price_paise"], None, resolve_point(b["requirement"]["location"]))
    c = Candidate(s.listing_id, s.farmer_id, "Tomato", Decimal(b["listing"]["available_kg"]), b["listing"]["price_paise"],
                  Grade(b["listing"]["grade"]), b["listing"]["location"], resolve_point(b["listing"]["location"]), None)
    again = score_candidate(req, c, s.distance_km, s.distance_km == 0.0)
    assert again.score == s.score and again.reasons == s.reasons and b["weights"] == WEIGHTS


def test_total_available():
    assert total_available([score(cand(qty=100)), score(cand(qty=250))]) == Decimal(350) and total_available([]) == 0


def test_geo_helpers():
    assert {canonical_city(x) for x in ("Bangalore", "BENGALURU", "Yeshwanthpur, Bengaluru", "Bengaluru Urban")} == {"bengaluru"}
    assert canonical_city("Xyzville") is None and canonical_city(None) is None
    a, b = resolve_point("Bengaluru"), resolve_point("Pune")
    assert abs(haversine_km(a, b) - haversine_km(b, a)) < 1e-6 and 700 < haversine_km(a, b) < 900
    assert resolve_point("Xyzville", 12.0, 77.0).lat == 12.0 and resolve_point("Xyzville") is None


def test_quantity_formatting_never_shows_trailing_zeros():
    from app.utils.money import fmt_kg
    assert [fmt_kg(Decimal(x)) for x in ("200.000", "500", "12.500", "0.250", "1000.000", "5E+2")] == ["200", "500", "12.5", "0.25", "1000", "500"]
    s = score(Candidate(uuid.uuid4(), uuid.uuid4(), "Tomato", Decimal("250.000"), 2850, Grade.A, "Bengaluru", BLR, None),
              Requirement("Tomato", Decimal("500.000"), Grade.A, "Bangalore", 3500, None, BLR))
    assert "250 kg available of 500 kg requested" in s.reasons[1]["detail"]
