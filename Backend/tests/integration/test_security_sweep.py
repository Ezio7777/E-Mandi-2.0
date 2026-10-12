"""Stage 19: security sweeps driven by the OpenAPI schema, so a newly added route is covered automatically."""
import json
import re
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import create_access_token
from tests.integration.conftest import bearer
from tests.integration.test_grading import make_admin
from tests.integration.test_listings import create
from tests.integration.test_matching_agent import buyer, farmer, mk

PUBLIC = {("POST", "/api/v1/auth/register"), ("POST", "/api/v1/auth/login"), ("POST", "/api/v1/auth/otp/request"),
          ("POST", "/api/v1/auth/otp/verify"), ("POST", "/api/v1/auth/google"), ("POST", "/api/v1/auth/refresh"),
          ("POST", "/api/v1/auth/logout"), ("GET", "/api/v1/auth/demo"), ("POST", "/api/v1/auth/demo"),
          ("POST", "/api/v1/auth/demo/{kind}"), ("POST", "/api/v1/payments/webhook")}
ADMIN_ONLY = ("/api/v1/admin", "/api/v1/audit", "/api/v1/analytics")
UUID0 = "00000000-0000-4000-8000-000000000000"


def operations(app):
    for path, item in app.openapi()["paths"].items():
        for method in item:
            if path.startswith("/api/v1"):
                yield method.upper(), path


def fill(path):
    return re.sub(r"\{(\w+)\}", lambda m: "farmer" if m.group(1) == "kind" else ("CROP_GRADING" if m.group(1) == "agent" else UUID0), path)


async def call(client, method, path, headers=None):
    return await client.request(method, fill(path), headers=headers or {}, json={} if method in {"POST", "PATCH", "PUT"} else None)


def token(user_id, role="FARMER", secret=None, exp_delta=timedelta(minutes=10), **over):
    s = get_settings()
    now = datetime.now(UTC)
    claims = {"sub": str(user_id), "role": role, "sid": str(uuid.uuid4()), "iss": s.JWT_ISSUER, "iat": now, "exp": now + exp_delta,
              "typ": "access", "jti": uuid.uuid4().hex, **over}
    return jwt.encode(claims, secret or s.JWT_SECRET.get_secret_value(), algorithm="HS256")


async def test_every_non_public_route_requires_authentication(app_ctx, client):
    checked = 0
    for method, path in operations(app_ctx):
        if (method, path) in PUBLIC:
            continue
        r = await call(client, method, path)
        assert r.status_code == 401, f"{method} {path} -> {r.status_code}"
        assert r.json()["error"]["code"]
        checked += 1
    assert checked > 80


async def test_forged_expired_and_garbage_tokens_are_rejected_everywhere(app_ctx, client, db):
    _, fid = await farmer(client, 1)
    bad = {
        "wrong_key": token(fid, secret="x" * 40),
        "expired": token(fid, exp_delta=timedelta(minutes=-5)),
        "unknown_session": token(fid),
        "garbage": "not.a.jwt",
        "alg_none": jwt.encode({"sub": str(fid), "role": "ADMIN", "exp": 9999999999}, None, algorithm="none"),
    }
    for name, t in bad.items():
        for path in ("/api/v1/auth/me", "/api/v1/listings/mine", "/api/v1/admin/agents"):
            r = await client.get(path, headers={"Authorization": f"Bearer {t}"})
            assert r.status_code == 401, f"{name} {path} -> {r.status_code}"
    for h in ({"Authorization": "Basic abc"}, {"Authorization": "Bearer"}, {"Authorization": ""}):
        assert (await client.get("/api/v1/auth/me", headers=h)).status_code == 401


async def test_role_escalation_via_token_claim_is_ignored(app_ctx, client, db):
    """A validly-signed token that CLAIMS ADMIN but whose session/user is a farmer must not gain admin access."""
    fh, fid = await farmer(client, 1)
    t = token(fid, role="ADMIN")
    r = await client.get("/api/v1/admin/agents", headers={"Authorization": f"Bearer {t}"})
    assert r.status_code in (401, 403)


async def test_admin_surface_rejects_farmers_and_buyers(app_ctx, client, db):
    fh, _ = await farmer(client, 1)
    bh, _ = await buyer(client, 1)
    n = 0
    for method, path in operations(app_ctx):
        if path.startswith(ADMIN_ONLY):
            for h in (fh, bh):
                r = await call(client, method, path, h)
                assert r.status_code == 403, f"{method} {path} -> {r.status_code}"
            n += 1
    assert n >= 20


async def test_role_gated_business_routes(app_ctx, client, db):
    fh, _ = await farmer(client, 1)
    bh, _ = await buyer(client, 1)
    # buyers cannot create listings / inventory edits; farmers cannot place orders / requirements
    assert (await client.post("/api/v1/listings", json={}, headers=bh)).status_code == 403
    assert (await client.post("/api/v1/orders", json={}, headers=fh)).status_code == 403
    assert (await client.post("/api/v1/requirements", json={}, headers=fh)).status_code == 403
    assert (await client.post("/api/v1/market/reports", json={}, headers=fh)).status_code == 403
    assert (await client.post("/api/v1/grading/listings/" + UUID0 + "/review", json={}, headers=fh)).status_code == 403


async def test_cross_user_access_is_hidden_as_404(app_ctx, client, db):
    f1h, f1 = await farmer(client, 1)
    f2h, _ = await farmer(client, 2)
    b1h, _ = await buyer(client, 1)
    b2h, _ = await buyer(client, 2)
    lid = await mk(db, f1, qty=500)
    d = await create(client, f1h)
    mine = d["id"]
    # another farmer cannot read/modify/submit/archive a draft they do not own
    for method, path in (("GET", f"/api/v1/listings/{mine}"), ("PATCH", f"/api/v1/listings/{mine}"),
                         ("POST", f"/api/v1/listings/{mine}/submit"), ("POST", f"/api/v1/listings/{mine}/archive"),
                         ("GET", f"/api/v1/grading/listings/{mine}"), ("GET", f"/api/v1/images/listing/{mine}")):
        r = await client.request(method, path, headers=f2h, json={} if method != "GET" else None)
        assert r.status_code in (403, 404), f"{method} {path} -> {r.status_code}"
    # orders: a third party sees nothing
    from tests.integration.test_orders import place
    o = await place(client, b1h, lid, 10, key="sec-order-key-1")
    assert o.status_code == 201, o.text
    oid = o.json()["data"]["id"]
    for h in (b2h, f2h):
        for path in (f"/api/v1/orders/{oid}", f"/api/v1/payments/order/{oid}"):
            assert (await client.get(path, headers=h)).status_code == 404, path
        assert (await client.post(f"/api/v1/orders/{oid}/cancel", headers=h)).status_code in (403, 404)
    listing = (await client.get("/api/v1/orders", headers=b2h)).json()["data"]
    assert listing == [] or listing == {"items": []} or all(i["id"] != oid for i in (listing if isinstance(listing, list) else listing.get("items", [])))


async def test_responses_never_leak_secrets_or_hashes(app_ctx, client, db):
    fh, _ = await farmer(client, 1)
    ah = await make_admin(db, client)
    blob = ""
    for path, h in (("/api/v1/auth/me", fh), ("/api/v1/users/me", fh), ("/api/v1/listings", fh), ("/api/v1/admin/agents", ah),
                    ("/api/v1/audit/logs", ah), ("/api/v1/admin/workers", ah), ("/api/v1/notifications", fh)):
        r = await client.get(path, headers=h)
        assert r.status_code == 200, path
        blob += r.text
    s = get_settings()
    for secret in (s.JWT_SECRET.get_secret_value(), s.AWS_SECRET_ACCESS_KEY.get_secret_value(), s.PAYMENT_KEY_SECRET.get_secret_value()):
        if secret:
            assert secret not in blob
    for field in ("password_hash", "code_hash", "token_hash", "refresh_token_hash", "api_key"):
        assert field not in blob


async def test_error_envelope_is_uniform_and_does_not_leak_internals(app_ctx, client):
    for r in (await client.get("/api/v1/nope"), await client.get("/api/v1/listings/not-a-uuid", headers={"Authorization": "Bearer x"}),
              await client.post("/api/v1/auth/login", content=b"{bad json", headers={"Content-Type": "application/json"}),
              await client.post("/api/v1/auth/login", json={"email": "a@b.co"}),
              await client.put("/api/v1/auth/login")):
        assert r.status_code in (401, 404, 405, 422), r.status_code
        body = r.json()
        err = body.get("error") or body
        assert "request_id" in json.dumps(body) or r.status_code == 405
        text = r.text.lower()
        for leak in ("traceback", "sqlalchemy", 'file "', "psycopg", "asyncpg"):
            assert leak not in text


async def test_injection_and_odd_inputs_are_handled_safely(app_ctx, client, db):
    fh, fid = await farmer(client, 1)
    bh, _ = await buyer(client, 1)
    await mk(db, fid)
    for evil in ("' OR 1=1--", "'; DROP TABLE listings;--", "%00", "<script>alert(1)</script>", "../../etc/passwd", "a" * 5000):
        r = await client.get("/api/v1/listings", params={"crop": evil, "location": evil}, headers=bh)
        assert r.status_code in (200, 422), (evil[:20], r.status_code)
        if r.status_code == 200:
            assert r.json()["data"] == [] or isinstance(r.json()["data"], (list, dict))
    assert (await client.get("/api/v1/listings", params={"limit": 100000}, headers=bh)).status_code == 422
    assert (await client.get("/api/v1/listings", params={"cursor": "garbage"}, headers=bh)).status_code in (400, 422)
    assert (await client.get("/api/v1/listings", headers=bh)).json()["data"], "table must still exist and hold the seeded row"


async def test_mass_assignment_is_rejected(app_ctx, client, db):
    fh, fid = await farmer(client, 1)
    r = await client.post("/api/v1/auth/register", json={"email": "evil@example.com", "password": "StrongPass123", "full_name": "E",
                                                         "role": "FARMER", "is_active": True, "is_admin": True, "id": UUID0})
    assert r.status_code in (201, 422)
    if r.status_code == 201:
        assert r.json()["data"]["user"]["role"] == "FARMER"
    r = await client.post("/api/v1/auth/register", json={"email": "adm@example.com", "password": "StrongPass123", "full_name": "A", "role": "ADMIN"})
    assert r.status_code == 422
    d = await create(client, fh)
    r = await client.patch(f"/api/v1/listings/{d['id']}", json={"status": "ACTIVE", "ai_grade": "A", "farmer_id": UUID0}, headers=fh)
    assert r.status_code in (400, 403, 422)


async def test_security_headers_and_cors(app_ctx, client):
    r = await client.get("/health/live")
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Cache-Control"] == "no-store" and r.headers["X-Request-ID"]
    ok = get_settings().cors_origins_list[0]
    pre = await client.options("/api/v1/auth/me", headers={"Origin": ok, "Access-Control-Request-Method": "GET",
                                                          "Access-Control-Request-Headers": "authorization"})
    assert pre.headers["access-control-allow-origin"] == ok and pre.headers["access-control-allow-origin"] != "*"
    evil = await client.options("/api/v1/auth/me", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in evil.headers
    simple = await client.get("/api/v1/auth/me", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in simple.headers


async def test_request_id_is_not_trusted_blindly(app_ctx, client):
    r = await client.get("/health/live", headers={"X-Request-ID": "x\r\nSet-Cookie: a=b"})
    assert "set-cookie" not in r.headers
    assert "\n" not in r.headers["X-Request-ID"]


async def test_webhook_rejects_bad_signature_without_touching_db(app_ctx, client, db):
    from sqlalchemy import func, select
    from app.models.payment_event import PaymentEvent
    for sig in (None, "", "deadbeef"):
        h = {"X-Mock-Event-Id": "evt_x", "Content-Type": "application/json"}
        if sig is not None:
            h["X-Mock-Signature"] = sig
        r = await client.post("/api/v1/payments/webhook", content=b'{"event":"payment.captured"}', headers=h)
        assert r.status_code == 401
    assert await db.scalar(select(func.count()).select_from(PaymentEvent)) == 0

