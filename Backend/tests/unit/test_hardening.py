"""Stage 22: production guards and the request body cap."""
import pytest
from app.core.body_limit import MaxBodySizeMiddleware
from app.core.config import Settings
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

PROD = {"ENVIRONMENT": "production", "JWT_SECRET": "j" * 40, "DATABASE_URL": "postgresql+asyncpg://u:realpw@db/x"}


def test_production_rejects_placeholder_database_password():
    with pytest.raises(ValueError, match="placeholder"):
        Settings(**{**PROD, "DATABASE_URL": "postgresql+asyncpg://emandi:change-me@db/x"})


def test_production_razorpay_requires_all_three_credentials():
    with pytest.raises(ValueError, match="razorpay"):
        Settings(**PROD, PAYMENT_PROVIDER="razorpay", PAYMENT_KEY_ID="k", PAYMENT_KEY_SECRET="", PAYMENT_WEBHOOK_SECRET="")
    with pytest.raises(ValueError, match="razorpay"):
        Settings(**PROD, PAYMENT_PROVIDER="razorpay", PAYMENT_KEY_ID="k", PAYMENT_KEY_SECRET="s", PAYMENT_WEBHOOK_SECRET="")
    ok = Settings(**PROD, PAYMENT_PROVIDER="razorpay", PAYMENT_KEY_ID="k", PAYMENT_KEY_SECRET="s", PAYMENT_WEBHOOK_SECRET="w")
    assert ok.is_production


async def _echo(request: Request) -> JSONResponse:
    return JSONResponse({"n": len(await request.body())})


class Passthrough(BaseHTTPMiddleware):  # mimics the app's BaseHTTPMiddleware layers (exceptions may arrive wrapped in a group)
    async def dispatch(self, request, call_next):
        return await call_next(request)


def tiny_app(limit: int = 1000) -> Starlette:
    app = Starlette(routes=[Route("/echo", _echo, methods=["POST"])])
    app.add_middleware(Passthrough)
    app.add_middleware(MaxBodySizeMiddleware, max_bytes=limit)
    return app


async def test_body_cap_content_length_path():
    async with AsyncClient(transport=ASGITransport(app=tiny_app()), base_url="http://t") as c:
        ok = await c.post("/echo", content=b"x" * 1000)
        big = await c.post("/echo", content=b"x" * 1001)
    assert ok.status_code == 200 and ok.json() == {"n": 1000}
    assert big.status_code == 413 and big.json()["error"]["code"] == "payload_too_large"


async def test_body_cap_chunked_stream_without_content_length():
    async def gen():
        for _ in range(5):
            yield b"y" * 400

    async with AsyncClient(transport=ASGITransport(app=tiny_app()), base_url="http://t") as c:
        r = await c.post("/echo", content=gen())
    assert r.status_code == 413


async def test_body_cap_ignores_non_http_scopes_and_get():
    async with AsyncClient(transport=ASGITransport(app=tiny_app()), base_url="http://t") as c:
        r = await c.get("/echo")
    assert r.status_code == 405  # reaches the router untouched
