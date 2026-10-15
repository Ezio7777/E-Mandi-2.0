import uuid

import jwt
import pytest
from app.core.config import Settings
from app.core.errors import UnauthorizedError
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_otp,
    hash_otp,
    hash_password,
    hash_token,
    verify_password,
)

S = Settings(ENVIRONMENT="test", JWT_SECRET="unit-test-secret-unit-test-secret-000000")


def test_password_hash_roundtrip():
    h = hash_password("CorrectHorse9")
    assert h.startswith("$argon2id$") and verify_password("CorrectHorse9", h)
    assert not verify_password("wrong", h)
    assert not verify_password("anything", None)


def test_jwt_roundtrip_and_claims():
    uid, sid = uuid.uuid4(), uuid.uuid4()
    tok, ttl = create_access_token(user_id=uid, role="BUYER", session_id=sid, demo=True, settings=S)
    c = decode_access_token(tok, S)
    assert (c.user_id, c.session_id, c.role, c.demo) == (uid, sid, "BUYER", True) and ttl == 900


def test_jwt_rejects_tamper_wrong_key_and_alg_none():
    tok, _ = create_access_token(user_id=uuid.uuid4(), role="BUYER", session_id=uuid.uuid4(), settings=S)
    with pytest.raises(UnauthorizedError):
        decode_access_token(tok + "x", S)
    other = Settings(ENVIRONMENT="test", JWT_SECRET="another-secret-another-secret-another-0000")
    with pytest.raises(UnauthorizedError):
        decode_access_token(tok, other)
    unsigned = jwt.encode({"sub": str(uuid.uuid4()), "sid": str(uuid.uuid4()), "iss": S.JWT_ISSUER, "iat": 1,
                           "exp": 9999999999}, None, algorithm="none")
    with pytest.raises(UnauthorizedError):
        decode_access_token(unsigned, S)


def test_refresh_token_hash_and_otp():
    assert hash_token("abc") == hash_token("abc") != hash_token("abd")
    otp, cid = generate_otp(6), uuid.uuid4()
    assert len(otp) == 6 and otp.isdigit()
    assert hash_otp(otp, cid, S) != hash_otp(otp, uuid.uuid4(), S)  # bound to challenge


def test_production_config_guards():
    with pytest.raises(ValueError):
        Settings(ENVIRONMENT="production", JWT_SECRET="short")
    with pytest.raises(ValueError):
        Settings(ENVIRONMENT="test", CORS_ORIGINS="*")
    assert Settings(ENVIRONMENT="production", JWT_SECRET="x" * 40, DATABASE_URL="postgresql+asyncpg://u:realpw@db/x").is_production
