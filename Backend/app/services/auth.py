"""Authentication: password, OTP, Google OIDC, demo login, refresh rotation, logout.

Rules enforced here (never in routes):
- Role/email are never taken from the client for existing identities. New self-service accounts can
  only be FARMER or BUYER (schema-enforced); ADMIN only exists via seeding/admin tooling.
- Refresh tokens are opaque, stored hashed, rotated on every use; reuse of a rotated token revokes the family.
- Every state change writes an audit row inside the same transaction.
"""
import uuid
from dataclasses import dataclass
from datetime import timedelta

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import transactional
from app.core.errors import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    UnauthorizedError,
)
from app.core.logging import get_logger
from app.core.rate_limit import check_rate_limit
from app.core.security import (
    constant_time_equals,
    create_access_token,
    generate_otp,
    generate_refresh_token,
    hash_otp,
    hash_password,
    hash_token,
    password_needs_rehash,
    verify_password,
)
from app.integrations.google.oidc import GoogleIdentityVerifier
from app.integrations.sms import OTPSender
from app.models.enums import AuthProvider, OtpPurpose, UserRole
from app.models.otp_challenge import OtpChallenge
from app.models.session import Session
from app.models.user import User
from app.models.user_profile import UserProfile
from app.repositories.otp import OtpRepository
from app.repositories.session import SessionRepository
from app.repositories.user import UserRepository
from app.schemas.auth import RegisterRequest
from app.services.audit import Actor, AuditService, RequestContext
from app.utils.time import utcnow

log = get_logger(__name__)

DEMO_ACCOUNTS: dict[str, tuple[str, UserRole, str]] = {
    "farmer": ("demo.farmer@e-mandi.demo", UserRole.FARMER, "Demo Farmer"),
    "buyer": ("demo.buyer@e-mandi.demo", UserRole.BUYER, "Demo Buyer"),
    "admin": ("demo.admin@e-mandi.demo", UserRole.ADMIN, "Demo Admin"),
}


class InvalidCredentials(UnauthorizedError):
    message = "Invalid credentials"


class DemoNotSeeded(AppError):
    status_code, code, message = 503, "demo_not_seeded", "Demo data has not been seeded"


class OtpInvalid(UnauthorizedError):
    code, message = "otp_invalid", "Invalid or expired code"


@dataclass(frozen=True)
class AuthResult:
    access_token: str
    refresh_token: str
    expires_in: int
    user: User
    is_demo: bool = False


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings, *, redis: Redis | None = None,
                 google: GoogleIdentityVerifier | None = None, otp_sender: OTPSender | None = None) -> None:
        self.session, self.settings, self.redis = session, settings, redis
        self.google, self.otp_sender = google, otp_sender
        self.users, self.sessions, self.otps = UserRepository(session), SessionRepository(session), OtpRepository(session)
        self.audit = AuditService(session)

    # ---------- helpers ----------
    async def _throttle(self, name: str, ident: str, limit: int, window: int) -> None:
        if self.redis is None:
            return
        try:
            ok, retry = await check_rate_limit(self.redis, f"rl:{name}:{ident}", limit, window)
        except Exception as exc:
            log.warning("throttle_backend_error", name=name, error=str(exc))
            return
        if not ok:
            raise RateLimitError(headers={"Retry-After": str(retry)})

    def _issue(self, user: User, ctx: RequestContext, *, family_id: uuid.UUID | None = None,
               demo: bool = False) -> AuthResult:
        """Adds a Session row; caller must be inside a transaction."""
        refresh = generate_refresh_token()
        sess = Session(
            id=uuid.uuid4(), user_id=user.id, family_id=family_id or uuid.uuid4(),
            refresh_token_hash=hash_token(refresh), is_demo=demo,
            expires_at=utcnow() + timedelta(days=self.settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
            created_ip=ctx.ip, user_agent=(ctx.user_agent or "")[:300] or None)
        self.session.add(sess)
        access, ttl = create_access_token(user_id=user.id, role=user.role.value, session_id=sess.id,
                                          demo=demo, settings=self.settings)
        return AuthResult(access, refresh, ttl, user, demo)

    @staticmethod
    def _assert_active(user: User) -> None:
        if not user.is_active:
            raise ForbiddenError("This account is disabled")

    def _new_user(self, **kw) -> User:
        user = User(**kw)
        user.profile = UserProfile(display_name=kw.get("full_name"))
        return user

    # ---------- password ----------
    async def register(self, data: RegisterRequest, ctx: RequestContext) -> AuthResult:
        email = data.email.lower()
        async with transactional(self.session):
            if await self.users.get_by_email(email):
                raise ConflictError("An account with this email already exists")
            if data.phone and await self.users.get_by_phone(data.phone):
                raise ConflictError("An account with this phone number already exists")
            user = await self.users.add(self._new_user(
                email=email, phone=data.phone, password_hash=hash_password(data.password),
                full_name=data.full_name.strip(), role=UserRole(data.role),
                auth_provider=AuthProvider.LOCAL, email_verified=False, last_login_at=utcnow()))
            self.audit.record(action="auth.register", entity_type="user", entity_id=user.id,
                              actor=Actor(user.id, user.role), ip=ctx.ip, metadata={"method": "password"})
            return self._issue(user, ctx)

    async def login_password(self, email: str, password: str, ctx: RequestContext) -> AuthResult:
        email = email.lower()
        await self._throttle("login_id", email, 10, 900)  # per-account throttle on top of per-IP
        user = await self.users.get_by_email(email)
        # verify_password burns equal time when user/hash is missing (no user enumeration by timing)
        valid = verify_password(password, user.password_hash if user else None)
        if not user or not valid:
            raise InvalidCredentials()
        self._assert_active(user)
        async with transactional(self.session):
            if user.password_hash and password_needs_rehash(user.password_hash):
                user.password_hash = hash_password(password)
            user.last_login_at = utcnow()
            self.audit.record(action="auth.login", entity_type="user", entity_id=user.id,
                              actor=Actor(user.id, user.role), ip=ctx.ip, metadata={"method": "password"})
            return self._issue(user, ctx)

    # ---------- OTP ----------
    async def request_otp(self, phone: str, ctx: RequestContext) -> tuple[uuid.UUID, int]:
        if self.otp_sender is None:
            raise AppError("OTP delivery is not configured")
        await self._throttle("otp_phone", phone, 3, 600)
        code = generate_otp(self.settings.OTP_LENGTH)
        challenge_id = uuid.uuid4()
        async with transactional(self.session):
            await self.otps.add(OtpChallenge(
                id=challenge_id, phone=phone, purpose=OtpPurpose.LOGIN,
                code_hash=hash_otp(code, challenge_id, self.settings),
                expires_at=utcnow() + timedelta(seconds=self.settings.OTP_TTL_SECONDS), created_ip=ctx.ip))
            self.audit.record(action="auth.otp_requested", entity_type="phone", ip=ctx.ip,
                              metadata={"challenge_id": str(challenge_id)})
        await self.otp_sender.send(phone, code)  # after commit: never send a code we did not persist
        # Same response whether or not the phone is registered (no enumeration).
        return challenge_id, self.settings.OTP_TTL_SECONDS

    async def verify_otp(self, challenge_id: uuid.UUID, code: str, role: str, full_name: str | None,
                         ctx: RequestContext) -> AuthResult:
        failure: AppError | None = None
        result: AuthResult | None = None
        async with transactional(self.session):
            ch = await self.otps.get_for_update(challenge_id)
            now = utcnow()
            if ch is None or ch.consumed_at or ch.expires_at < now or ch.attempts >= self.settings.OTP_MAX_ATTEMPTS:
                failure = OtpInvalid()
            else:
                ch.attempts += 1  # persisted even on failure (commit happens, error raised after)
                if not constant_time_equals(ch.code_hash, hash_otp(code, ch.id, self.settings)):
                    failure = OtpInvalid()
                else:
                    ch.consumed_at = now
                    user = await self.users.get_by_phone(ch.phone)
                    created = user is None
                    if user is None:
                        user = await self.users.add(self._new_user(
                            phone=ch.phone, full_name=(full_name or "User").strip(), role=UserRole(role),
                            auth_provider=AuthProvider.PHONE, phone_verified=True))
                    else:
                        self._assert_active(user)
                        user.phone_verified = True
                    user.last_login_at = now
                    self.audit.record(action="auth.register" if created else "auth.login", entity_type="user",
                                      entity_id=user.id, actor=Actor(user.id, user.role), ip=ctx.ip,
                                      metadata={"method": "otp"})
                    result = self._issue(user, ctx)
        if failure:
            raise failure
        assert result is not None
        return result

    # ---------- Google ----------
    async def login_google(self, credential: str, role: str, ctx: RequestContext) -> AuthResult:
        if self.google is None:
            raise AppError("Google login is not configured")
        ident = await self.google.verify(credential)  # signature/iss/aud/exp/email_verified
        async with transactional(self.session):
            user = await self.users.get_by_google_sub(ident.sub)
            created = False
            if user is None:
                user = await self.users.get_by_email(ident.email)
                if user is not None:
                    # Link to existing account by Google-VERIFIED email. If the local account's email was never
                    # verified, someone may have pre-registered it: drop the password and sessions (anti pre-hijack).
                    if not user.email_verified:
                        user.password_hash = None
                        await self.sessions.revoke_all_for_user(user.id, utcnow())
                    user.google_sub, user.email_verified = ident.sub, True
                else:
                    created = True
                    user = await self.users.add(self._new_user(
                        email=ident.email, google_sub=ident.sub, full_name=ident.name or ident.email.split("@")[0],
                        role=UserRole(role), auth_provider=AuthProvider.GOOGLE, email_verified=True))
            self._assert_active(user)
            user.last_login_at = utcnow()
            self.audit.record(action="auth.register" if created else "auth.login", entity_type="user",
                              entity_id=user.id, actor=Actor(user.id, user.role), ip=ctx.ip,
                              metadata={"method": "google"})
            return self._issue(user, ctx)

    # ---------- demo ----------
    async def demo_login(self, kind: str, ctx: RequestContext) -> AuthResult:
        if not self.settings.DEMO_MODE:
            raise NotFoundError()  # do not advertise the feature when disabled
        if kind not in DEMO_ACCOUNTS:
            raise NotFoundError()
        email = DEMO_ACCOUNTS[kind][0]
        user = await self.users.get_by_email(email)
        if user is None or not user.is_demo:  # seeded users only; NEVER created here
            raise DemoNotSeeded()
        self._assert_active(user)
        async with transactional(self.session):
            user.last_login_at = utcnow()
            self.audit.record(action="auth.demo_login", entity_type="user", entity_id=user.id,
                              actor=Actor(user.id, user.role), ip=ctx.ip, metadata={"demo": True, "kind": kind})
            return self._issue(user, ctx, demo=True)

    # ---------- refresh / logout ----------
    async def refresh(self, refresh_token: str, ctx: RequestContext) -> AuthResult:
        reuse_detected = False
        result: AuthResult | None = None
        async with transactional(self.session):
            sess = await self.sessions.get_by_token_hash(hash_token(refresh_token), for_update=True)
            now = utcnow()
            if sess is None:
                pass
            elif sess.rotated_at is not None or sess.revoked_at is not None:
                # A rotated/revoked token was replayed: assume theft, kill the whole family.
                await self.sessions.revoke_family(sess.family_id, now)
                self.audit.record(action="auth.refresh_reuse_detected", entity_type="session", entity_id=sess.id,
                                  actor=Actor(sess.user_id, None), ip=ctx.ip,
                                  metadata={"family_id": str(sess.family_id)})
                reuse_detected = True
            elif sess.expires_at < now:
                pass
            else:
                user = await self.users.get(sess.user_id)
                if user is not None and user.is_active:
                    sess.rotated_at, sess.last_used_at = now, now
                    result = self._issue(user, ctx, family_id=sess.family_id, demo=sess.is_demo)
        if result is None:
            raise UnauthorizedError("Session expired, please sign in again" if not reuse_detected
                                    else "Session is no longer valid, please sign in again")
        return result

    async def logout(self, refresh_token: str, ctx: RequestContext) -> None:
        async with transactional(self.session):
            sess = await self.sessions.get_by_token_hash(hash_token(refresh_token))
            if sess is not None:
                await self.sessions.revoke_family(sess.family_id, utcnow())
                self.audit.record(action="auth.logout", entity_type="session", entity_id=sess.id,
                                  actor=Actor(sess.user_id, None), ip=ctx.ip)

    async def logout_all(self, user: User, ctx: RequestContext) -> None:
        async with transactional(self.session):
            await self.sessions.revoke_all_for_user(user.id, utcnow())
            self.audit.record(action="auth.logout_all", entity_type="user", entity_id=user.id,
                              actor=Actor(user.id, user.role), ip=ctx.ip)
