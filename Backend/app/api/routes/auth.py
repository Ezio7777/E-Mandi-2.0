"""Auth routes (thin): parse -> service -> envelope."""
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.dependencies import (
    CurrentUser, RedisDep, RequestContextDep, SessionDep, SettingsDep, get_google_verifier, get_otp_sender,
)
from app.core.rate_limit import rate_limit
from app.integrations.google.oidc import GoogleIdentityVerifier
from app.integrations.sms import OTPSender
from app.schemas.auth import (
    GoogleLoginRequest, LoginRequest, OtpChallengeOut, OtpRequest, OtpVerifyRequest, RefreshRequest,
    RegisterRequest, TokenResponse,
)
from app.schemas.common import Envelope
from app.services.auth import AuthResult, AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def get_auth_service(session: SessionDep, settings: SettingsDep, redis: RedisDep,
                     google: Annotated[GoogleIdentityVerifier, Depends(get_google_verifier)],
                     otp: Annotated[OTPSender, Depends(get_otp_sender)]) -> AuthService:
    return AuthService(session, settings, redis=redis, google=google, otp_sender=otp)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def token_response(r: AuthResult) -> Envelope[TokenResponse]:
    return Envelope(data=TokenResponse.model_validate({
        "access_token": r.access_token, "refresh_token": r.refresh_token, "expires_in": r.expires_in,
        "is_demo": r.is_demo, "user": r.user}, from_attributes=True))


@router.post("/register", response_model=Envelope[TokenResponse], status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(rate_limit("register", 10, 3600))])
async def register(body: RegisterRequest, svc: AuthServiceDep, ctx: RequestContextDep):
    return token_response(await svc.register(body, ctx))


@router.post("/login", response_model=Envelope[TokenResponse],
             dependencies=[Depends(rate_limit("login", 20, 60))])
async def login(body: LoginRequest, svc: AuthServiceDep, ctx: RequestContextDep):
    return token_response(await svc.login_password(body.email, body.password, ctx))


@router.post("/otp/request", response_model=Envelope[OtpChallengeOut],
             dependencies=[Depends(rate_limit("otp_request", 5, 600))])
async def otp_request(body: OtpRequest, svc: AuthServiceDep, ctx: RequestContextDep):
    cid, ttl = await svc.request_otp(body.phone, ctx)
    return Envelope(data=OtpChallengeOut(challenge_id=cid, expires_in=ttl))


@router.post("/otp/verify", response_model=Envelope[TokenResponse],
             dependencies=[Depends(rate_limit("otp_verify", 15, 600))])
async def otp_verify(body: OtpVerifyRequest, svc: AuthServiceDep, ctx: RequestContextDep):
    return token_response(await svc.verify_otp(body.challenge_id, body.code, body.role, body.full_name, ctx))


@router.post("/google", response_model=Envelope[TokenResponse],
             dependencies=[Depends(rate_limit("google", 20, 60))])
async def google_login(body: GoogleLoginRequest, svc: AuthServiceDep, ctx: RequestContextDep):
    return token_response(await svc.login_google(body.credential, body.role, ctx))


@router.post("/refresh", response_model=Envelope[TokenResponse],
             dependencies=[Depends(rate_limit("refresh", 30, 60))])
async def refresh(body: RefreshRequest, svc: AuthServiceDep, ctx: RequestContextDep):
    return token_response(await svc.refresh(body.refresh_token, ctx))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest, svc: AuthServiceDep, ctx: RequestContextDep) -> None:
    await svc.logout(body.refresh_token, ctx)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(user: CurrentUser, svc: AuthServiceDep, ctx: RequestContextDep) -> None:
    await svc.logout_all(user, ctx)


# Frontend-contract alias: GET /auth/me (same payload as GET /users/me)
from app.schemas.user import UserOut  # noqa: E402


@router.get("/me", response_model=Envelope[UserOut])
async def me(user: CurrentUser):
    return Envelope(data=UserOut.model_validate(user))
