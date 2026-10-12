import uuid
from datetime import timedelta

import jwt
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.dependencies import forbid_demo, require_roles
from app.core.security import create_access_token
from app.integrations.google.oidc import GoogleIdentity
from app.models.audit_log import AuditLog
from app.models.enums import UserRole
from app.models.user import User
from tests.integration.conftest import REG, bearer, register

A = "/api/v1/auth"


async def test_register_login_me(client):
    tokens = await register(client)
    assert tokens["user"]["role"] == "FARMER" and tokens["is_demo"] is False
    assert "password" not in str(tokens).lower()
    r = await client.post(f"{A}/login", json={"email": REG["email"], "password": REG["password"]})
    assert r.status_code == 200
    me = await client.get("/api/v1/users/me", headers=bearer(r.json()["data"]))
    assert me.json()["data"]["email"] == REG["email"]


async def test_register_validation_and_role_lockdown(client):
    r = await client.post(f"{A}/register", json={**REG, "role": "ADMIN"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    assert any(d["field"] == "role" for d in r.json()["error"]["details"])
    assert (await client.post(f"{A}/register", json={**REG, "password": "short"})).status_code == 422
    assert (await client.post(f"{A}/register", json={**REG, "password": "onlyletters!!"})).status_code == 422
    await register(client)
    dup = await client.post(f"{A}/register", json=REG)
    assert dup.status_code == 409


async def test_login_failure_is_uniform(client):
    await register(client)
    bad_pw = await client.post(f"{A}/login", json={"email": REG["email"], "password": "wrong-pass-1"})
    no_user = await client.post(f"{A}/login", json={"email": "ghost@example.com", "password": "wrong-pass-1"})
    assert bad_pw.status_code == no_user.status_code == 401
    assert bad_pw.json()["error"]["message"] == no_user.json()["error"]["message"]


async def test_protected_endpoint_requires_valid_token(client):
    assert (await client.get("/api/v1/users/me")).status_code == 401
    assert (await client.get("/api/v1/users/me", headers={"Authorization": "Bearer garbage"})).status_code == 401
    s = get_settings()
    forged = jwt.encode({"sub": str(uuid.uuid4()), "sid": str(uuid.uuid4()), "iss": s.JWT_ISSUER,
                         "iat": 1, "exp": 9999999999, "typ": "access", "role": "ADMIN"}, "wrong-key" * 5, "HS256")
    assert (await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {forged}"})).status_code == 401
    none_alg = jwt.encode({"sub": str(uuid.uuid4()), "sid": str(uuid.uuid4()), "iss": s.JWT_ISSUER,
                           "exp": 9999999999, "iat": 1}, None, algorithm="none")
    assert (await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {none_alg}"})).status_code == 401


async def test_expired_token_rejected(client, db):
    tokens = await register(client)
    u = (await db.scalars(select(User))).one()
    import app.core.security as sec
    s = get_settings().model_copy(update={"JWT_ACCESS_TOKEN_EXPIRE_MINUTES": -1})
    tok, _ = sec.create_access_token(user_id=u.id, role="FARMER", session_id=uuid.uuid4(), settings=s)
    assert (await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {tok}"})).status_code == 401
    assert tokens


async def test_refresh_rotation_and_reuse_detection(client):
    t1 = await register(client)
    r2 = await client.post(f"{A}/refresh", json={"refresh_token": t1["refresh_token"]})
    assert r2.status_code == 200
    t2 = r2.json()["data"]
    assert t2["refresh_token"] != t1["refresh_token"]
    assert (await client.get("/api/v1/users/me", headers=bearer(t2))).status_code == 200
    # replay the OLD (rotated) token => theft assumed => whole family revoked
    replay = await client.post(f"{A}/refresh", json={"refresh_token": t1["refresh_token"]})
    assert replay.status_code == 401
    assert (await client.post(f"{A}/refresh", json={"refresh_token": t2["refresh_token"]})).status_code == 401
    assert (await client.get("/api/v1/users/me", headers=bearer(t2))).status_code == 401


async def test_logout_revokes_session(client):
    t = await register(client)
    assert (await client.post(f"{A}/logout", json={"refresh_token": t["refresh_token"]})).status_code == 204
    assert (await client.get("/api/v1/users/me", headers=bearer(t))).status_code == 401
    assert (await client.post(f"{A}/refresh", json={"refresh_token": t["refresh_token"]})).status_code == 401


async def test_logout_all(client):
    await register(client)
    a = (await client.post(f"{A}/login", json={"email": REG["email"], "password": REG["password"]})).json()["data"]
    b = (await client.post(f"{A}/login", json={"email": REG["email"], "password": REG["password"]})).json()["data"]
    assert (await client.post(f"{A}/logout-all", headers=bearer(a))).status_code == 204
    assert (await client.get("/api/v1/users/me", headers=bearer(b))).status_code == 401


async def test_disabled_user_blocked(client, db):
    t = await register(client)
    u = (await db.scalars(select(User))).one()
    u.is_active = False
    await db.commit()
    assert (await client.get("/api/v1/users/me", headers=bearer(t))).status_code == 403
    assert (await client.post(f"{A}/login", json={"email": REG["email"], "password": REG["password"]})).status_code == 403
    assert (await client.post(f"{A}/refresh", json={"refresh_token": t["refresh_token"]})).status_code == 401


async def test_rbac_dependency(app_ctx, client):
    from fastapi import APIRouter, Depends
    r = APIRouter()

    @r.get("/_t/admin", dependencies=[Depends(require_roles(UserRole.ADMIN))])
    async def admin_only():  # noqa: ANN202
        return {"ok": True}

    @r.post("/_t/destructive", dependencies=[Depends(forbid_demo)])
    async def destructive():  # noqa: ANN202
        return {"ok": True}

    app_ctx.include_router(r)
    farmer = await register(client)
    assert (await client.get("/_t/admin", headers=bearer(farmer))).status_code == 403
    assert (await client.get("/_t/admin")).status_code == 401
    assert (await client.post("/_t/destructive", headers=bearer(farmer))).status_code == 200


async def test_profile_update(client):
    t = await register(client)
    r = await client.patch("/api/v1/users/me/profile", headers=bearer(t),
                           json={"city": "Bengaluru", "preferred_language": "kn"})
    assert r.json()["data"]["profile"]["preferred_language"] == "kn"
    bad = await client.patch("/api/v1/users/me/profile", headers=bearer(t), json={"role": "ADMIN"})
    assert bad.status_code == 422  # extra fields forbidden: role cannot be changed here
    assert (await client.patch("/api/v1/users/me/profile", headers=bearer(t), json={"preferred_language": "fr"})).status_code == 422


# ---------------------------- Google ----------------------------
def _gid(app_ctx, email="g@example.com", sub="sub-1"):
    app_ctx.state.fake_google.identity = GoogleIdentity(sub, email, True, "G User", None)


async def test_google_creates_user_with_safe_role(app_ctx, client):
    _gid(app_ctx)
    r = await client.post(f"{A}/google", json={"credential": "x" * 30})
    assert r.status_code == 200 and r.json()["data"]["user"]["role"] == "BUYER"
    r = await client.post(f"{A}/google", json={"credential": "x" * 30, "role": "FARMER"})
    assert r.json()["data"]["user"]["role"] == "BUYER"  # existing identity: requested role ignored
    assert (await client.post(f"{A}/google", json={"credential": "x" * 30, "role": "ADMIN"})).status_code == 422


async def test_google_farmer_onboarding_and_bad_credential(app_ctx, client):
    _gid(app_ctx, "farmer@example.com", "sub-2")
    r = await client.post(f"{A}/google", json={"credential": "x" * 30, "role": "FARMER"})
    assert r.json()["data"]["user"]["role"] == "FARMER"
    assert (await client.post(f"{A}/google", json={"credential": "bad" + "x" * 30})).status_code == 401


async def test_google_prehijack_protection(app_ctx, client, db):
    await register(client, email="victim@example.com", password="AttackerPass1")
    _gid(app_ctx, "victim@example.com", "sub-victim")
    assert (await client.post(f"{A}/google", json={"credential": "x" * 30})).status_code == 200
    u = (await db.scalars(select(User).where(User.email == "victim@example.com"))).one()
    await db.refresh(u)
    assert u.password_hash is None and u.google_sub == "sub-victim" and u.email_verified
    r = await client.post(f"{A}/login", json={"email": "victim@example.com", "password": "AttackerPass1"})
    assert r.status_code == 401


# ---------------------------- OTP ----------------------------
async def test_otp_flow_creates_account(app_ctx, client):
    r = await client.post(f"{A}/otp/request", json={"phone": "9876543210"})
    assert r.status_code == 200
    cid = r.json()["data"]["challenge_id"]
    code = app_ctx.state.fake_otp.codes["+919876543210"]
    assert "code" not in r.json()["data"]
    bad = await client.post(f"{A}/otp/verify", json={"challenge_id": cid, "code": "000000" if code != "000000" else "111111"})
    assert bad.status_code == 401
    ok = await client.post(f"{A}/otp/verify", json={"challenge_id": cid, "code": code, "role": "FARMER", "full_name": "Sita"})
    assert ok.status_code == 200 and ok.json()["data"]["user"]["phone_verified"] is True
    replay = await client.post(f"{A}/otp/verify", json={"challenge_id": cid, "code": code})
    assert replay.status_code == 401  # consumed


async def test_otp_attempt_limit(app_ctx, client):
    cid = (await client.post(f"{A}/otp/request", json={"phone": "9876543211"})).json()["data"]["challenge_id"]
    code = app_ctx.state.fake_otp.codes["+919876543211"]
    wrong = "111111" if code != "111111" else "222222"
    for _ in range(get_settings().OTP_MAX_ATTEMPTS):
        assert (await client.post(f"{A}/otp/verify", json={"challenge_id": cid, "code": wrong})).status_code == 401
    # even the CORRECT code is now rejected
    assert (await client.post(f"{A}/otp/verify", json={"challenge_id": cid, "code": code})).status_code == 401


async def test_otp_request_throttled_per_phone(client):
    for _ in range(3):
        assert (await client.post(f"{A}/otp/request", json={"phone": "9876543212"})).status_code == 200
    assert (await client.post(f"{A}/otp/request", json={"phone": "9876543212"})).status_code == 429


async def test_invalid_phone_rejected(client):
    assert (await client.post(f"{A}/otp/request", json={"phone": "12345"})).status_code == 422


# ---------------------------- Demo ----------------------------
async def test_demo_login_uses_seeded_users_only(client, demo_users):
    r = await client.post(f"{A}/demo/farmer")
    d = r.json()["data"]
    assert r.status_code == 200 and d["is_demo"] is True and d["user"]["is_demo"] is True
    assert jwt.decode(d["access_token"], options={"verify_signature": False})["demo"] is True
    assert (await client.post(f"{A}/demo/superuser")).status_code == 422
    assert (await client.get(f"{A}/demo")).status_code == 200


async def test_demo_not_seeded_and_disabled(app_ctx, client):
    assert (await client.post(f"{A}/demo/admin")).status_code == 503
    from app.core.config import Settings, get_settings as gs
    app_ctx.dependency_overrides[gs] = lambda: Settings(DEMO_MODE=False, ENVIRONMENT="test")
    assert (await client.post(f"{A}/demo/admin")).status_code == 404
    assert (await client.get(f"{A}/demo")).status_code == 404


async def test_demo_session_blocked_from_destructive_actions(app_ctx, client, demo_users):
    from fastapi import APIRouter, Depends
    r = APIRouter()

    @r.post("/_t/ban", dependencies=[Depends(forbid_demo)])
    async def ban():  # noqa: ANN202
        return {"ok": True}

    app_ctx.include_router(r)
    tok = (await client.post(f"{A}/demo/admin")).json()["data"]
    assert (await client.post("/_t/ban", headers=bearer(tok))).status_code == 403


async def test_demo_login_rate_limited(client, demo_users):
    codes = [(await client.post(f"{A}/demo/buyer")).status_code for _ in range(12)]
    assert codes.count(200) == 10 and codes[-1] == 429


async def test_login_rate_limited_per_ip(client):
    codes = [(await client.post(f"{A}/login", json={"email": f"u{i}@example.com", "password": "x"})).status_code
             for i in range(22)]
    assert 429 in codes


# ---------------------------- Audit ----------------------------
async def test_auth_actions_are_audited(client, db):
    t = await register(client)
    await client.post(f"{A}/login", json={"email": REG["email"], "password": REG["password"]})
    await client.post(f"{A}/logout", json={"refresh_token": t["refresh_token"]})
    rows = (await db.scalars(select(AuditLog).order_by(AuditLog.timestamp))).all()
    assert [r.action for r in rows] == ["auth.register", "auth.login", "auth.logout"]
    assert all(r.request_id for r in rows) and rows[0].meta == {"method": "password"}
    assert "Sup3rSecret" not in str([r.meta for r in rows])


async def test_failed_action_leaves_no_audit_row(client, db):
    await register(client)
    await client.post(f"{A}/register", json=REG)  # 409
    count = len((await db.scalars(select(AuditLog))).all())
    assert count == 1


_ = (pytest, timedelta, create_access_token)
