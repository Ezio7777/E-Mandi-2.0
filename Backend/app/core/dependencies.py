"""Shared FastAPI dependencies (settings, redis, db). Auth deps are appended in Stage 5."""
from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_session

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


RedisDep = Annotated[Redis, Depends(get_redis)]


# ---------------------------------------------------------------------------------------------
# Auth dependencies (Stage 5)
# ---------------------------------------------------------------------------------------------
from collections.abc import Callable  # noqa: E402

from fastapi import Header  # noqa: E402
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # noqa: E402

from app.core.errors import ForbiddenError, UnauthorizedError  # noqa: E402
from app.core.rate_limit import client_ip  # noqa: E402
from app.core.security import AccessClaims, decode_access_token  # noqa: E402
from app.integrations.google.oidc import GoogleIdentityVerifier, GoogleOIDCVerifier  # noqa: E402
from app.integrations.sms import OTPSender, build_otp_sender  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.models.user import User  # noqa: E402
from app.repositories.session import SessionRepository  # noqa: E402
from app.repositories.user import UserRepository  # noqa: E402
from app.services.audit import RequestContext  # noqa: E402

_bearer = HTTPBearer(auto_error=False)


async def get_request_context(request: Request) -> RequestContext:
    return RequestContext(ip=client_ip(request), user_agent=request.headers.get("user-agent"))


RequestContextDep = Annotated[RequestContext, Depends(get_request_context)]


def get_google_verifier(request: Request, settings: SettingsDep) -> GoogleIdentityVerifier:
    verifier = getattr(request.app.state, "google_verifier", None)
    if verifier is None:
        verifier = GoogleOIDCVerifier(settings.GOOGLE_CLIENT_ID)
        request.app.state.google_verifier = verifier  # cache JWKS across requests
    return verifier


def get_otp_sender(request: Request, settings: SettingsDep) -> OTPSender:
    sender = getattr(request.app.state, "otp_sender", None)
    if sender is None:
        sender = build_otp_sender(settings)
        request.app.state.otp_sender = sender  # one boto3 client per process
    return sender


async def get_claims(request: Request,
                     creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> AccessClaims:
    if creds is None:
        raise UnauthorizedError(headers={"WWW-Authenticate": "Bearer"})  # type: ignore[arg-type]
    claims = decode_access_token(creds.credentials)
    request.state.user_id = str(claims.user_id)
    return claims


ClaimsDep = Annotated[AccessClaims, Depends(get_claims)]


async def get_current_user(claims: ClaimsDep, session: SessionDep) -> User:
    sess = await SessionRepository(session).get(claims.session_id)
    if sess is None or sess.revoked_at is not None or sess.user_id != claims.user_id:
        raise UnauthorizedError("Session is no longer valid")
    user = await UserRepository(session).get(claims.user_id)
    if user is None:
        raise UnauthorizedError("Session is no longer valid")
    if not user.is_active:
        raise ForbiddenError("This account is disabled")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[..., User]:
    """Route-level RBAC. Object-level ownership is still checked inside services."""
    allowed = set(roles)

    async def _dep(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise ForbiddenError()
        return user

    return _dep  # type: ignore[return-value]


async def forbid_demo(claims: ClaimsDep) -> None:
    """Attach to destructive/irreversible operations so demo sessions can never perform them."""
    if claims.demo:
        raise ForbiddenError("This action is disabled in demo mode")


_ = Header  # (kept for Idempotency-Key dependency added with orders/payments)


# ---------------------------------------------------------------------------------------------
# Storage dependencies (Stage 6)
# ---------------------------------------------------------------------------------------------
from app.integrations.aws.image_url_resolver import ImageUrlResolver, build_resolver  # noqa: E402
from app.integrations.aws.s3 import ObjectStorage, S3Storage  # noqa: E402


def get_storage(request: Request, settings: SettingsDep) -> ObjectStorage:
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        storage = S3Storage(settings)
        request.app.state.storage = storage  # one boto3 client per process
    return storage


def get_url_resolver(settings: SettingsDep, storage: Annotated[ObjectStorage, Depends(get_storage)]) -> ImageUrlResolver:
    return build_resolver(settings, storage)


# ---------------------------------------------------------------------------------------------
# Job queue dependency (Stage 8)
# ---------------------------------------------------------------------------------------------
from app.workers.queue import ArqJobQueue, JobQueue  # noqa: E402


def get_job_queue(request: Request, settings: SettingsDep) -> JobQueue:
    q = getattr(request.app.state, "job_queue", None)
    if q is None:
        q = ArqJobQueue(settings)
        request.app.state.job_queue = q
    return q


# ---------------------------------------------------------------------------------------------
# Embedding provider dependency (Stage 9)
# ---------------------------------------------------------------------------------------------
from app.services.embedding import EmbeddingProvider, build_embedding_provider  # noqa: E402


def get_embedding_provider(request: Request, settings: SettingsDep) -> EmbeddingProvider:
    p = getattr(request.app.state, "embedder", None)
    if p is None:
        p = build_embedding_provider(settings)
        request.app.state.embedder = p
    return p


# ---------------------------------------------------------------------------------------------
# Payment provider dependency (Stage 13)
# ---------------------------------------------------------------------------------------------
from app.integrations.payments.base import PaymentProvider  # noqa: E402
from app.integrations.payments.mock import MockPaymentProvider  # noqa: E402
from app.integrations.payments.razorpay import RazorpayProvider  # noqa: E402


def get_payment_provider(request: Request, settings: SettingsDep) -> PaymentProvider:
    p = getattr(request.app.state, "payment_provider", None)
    if p is None:
        p = RazorpayProvider(settings) if settings.PAYMENT_PROVIDER == "razorpay" else MockPaymentProvider(settings)
        request.app.state.payment_provider = p
    return p


# ---------------------------------------------------------------------------------------------
# Voice providers dependency (Stage 15)
# ---------------------------------------------------------------------------------------------
from app.services.voice import VoiceProviders, build_voice_providers  # noqa: E402


def get_voice_providers(request: Request, settings: SettingsDep) -> VoiceProviders:
    p = getattr(request.app.state, "voice_providers", None)
    if p is None:
        p = build_voice_providers(settings)
        request.app.state.voice_providers = p
    return p
