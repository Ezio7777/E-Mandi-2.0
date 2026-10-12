"""Recruiter demo login: seeded users only, rate limited, flagged is_demo in token + response."""
from typing import Literal

from fastapi import APIRouter, Depends

from app.api.routes.auth import AuthServiceDep, token_response
from app.core.dependencies import RequestContextDep, SettingsDep
from app.core.errors import NotFoundError
from app.core.rate_limit import rate_limit
from app.schemas.auth import DemoAccountOut, TokenResponse
from app.schemas.common import Envelope

router = APIRouter(prefix="/auth/demo", tags=["demo"])


@router.get("", response_model=Envelope[list[DemoAccountOut]])
async def list_demo_accounts(settings: SettingsDep):
    if not settings.DEMO_MODE:
        raise NotFoundError()
    return Envelope(data=[DemoAccountOut(kind="farmer", label="Try Demo Farmer"),
                          DemoAccountOut(kind="buyer", label="Try Demo Buyer"),
                          DemoAccountOut(kind="admin", label="Try Demo Admin")])


@router.post("/{kind}", response_model=Envelope[TokenResponse],
             dependencies=[Depends(rate_limit("demo_login", 10, 60))])
async def demo_login(kind: Literal["farmer", "buyer", "admin"], svc: AuthServiceDep, ctx: RequestContextDep):
    return token_response(await svc.demo_login(kind, ctx))


# Frontend-contract alias: POST /auth/demo  {"kind": "farmer|buyer|admin"}
from pydantic import BaseModel  # noqa: E402


class DemoLoginBody(BaseModel):
    kind: Literal["farmer", "buyer", "admin"]


@router.post("", response_model=Envelope[TokenResponse], dependencies=[Depends(rate_limit("demo_login", 10, 60))])
async def demo_login_body(body: DemoLoginBody, svc: AuthServiceDep, ctx: RequestContextDep):
    return token_response(await svc.demo_login(body.kind, ctx))
