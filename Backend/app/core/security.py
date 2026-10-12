"""Password hashing, JWT access tokens, opaque refresh tokens, OTP hashing."""
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings, get_settings
from app.core.errors import UnauthorizedError

_hasher = PasswordHasher()  # Argon2id defaults
# Used to equalise timing when the account does not exist.
_DUMMY_HASH = _hasher.hash("timing-equaliser")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    role: str
    session_id: uuid.UUID
    demo: bool
    jti: str


def create_access_token(*, user_id: uuid.UUID, role: str, session_id: uuid.UUID, demo: bool = False,
                        settings: Settings | None = None) -> tuple[str, int]:
    s = settings or get_settings()
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=s.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id), "role": role, "sid": str(session_id), "demo": demo,
        "jti": uuid.uuid4().hex, "iat": now, "exp": expires, "iss": s.JWT_ISSUER, "typ": "access",
    }
    token = jwt.encode(payload, s.JWT_SECRET.get_secret_value(), algorithm=s.JWT_ALGORITHM)
    return token, s.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60


def decode_access_token(token: str, settings: Settings | None = None) -> AccessClaims:
    s = settings or get_settings()
    try:
        data = jwt.decode(
            token, s.JWT_SECRET.get_secret_value(),
            algorithms=[s.JWT_ALGORITHM],  # pinned: never trust the token's own alg header
            issuer=s.JWT_ISSUER,
            options={"require": ["exp", "iat", "sub", "iss", "sid"]},
        )
        if data.get("typ") != "access":
            raise UnauthorizedError("Invalid token")
        return AccessClaims(uuid.UUID(data["sub"]), data["role"], uuid.UUID(data["sid"]),
                            bool(data.get("demo", False)), data.get("jti", ""))
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise UnauthorizedError("Invalid or expired token") from exc


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """SHA-256 is appropriate for high-entropy random tokens (not for passwords)."""
    return hashlib.sha256(token.encode()).hexdigest()


def generate_otp(length: int) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(length))


def hash_otp(otp: str, challenge_id: uuid.UUID, settings: Settings | None = None) -> str:
    s = settings or get_settings()
    key = s.JWT_SECRET.get_secret_value().encode()
    return hmac.new(key, f"{challenge_id}:{otp}".encode(), hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def sign_token(payload: dict, *, typ: str, ttl_seconds: int, settings: Settings | None = None) -> str:
    """Short-lived signed token for stateless server-issued grants (e.g. upload confirmation)."""
    s = settings or get_settings()
    now = datetime.now(UTC)
    body = {**payload, "typ": typ, "iat": now, "exp": now + timedelta(seconds=ttl_seconds), "iss": s.JWT_ISSUER}
    return jwt.encode(body, s.JWT_SECRET.get_secret_value(), algorithm=s.JWT_ALGORITHM)


def verify_signed_token(token: str, *, typ: str, settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    try:
        data = jwt.decode(token, s.JWT_SECRET.get_secret_value(), algorithms=[s.JWT_ALGORITHM], issuer=s.JWT_ISSUER,
                          options={"require": ["exp", "iat", "iss"]})
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Invalid or expired token") from exc
    if data.get("typ") != typ:
        raise UnauthorizedError("Invalid or expired token")
    return data
