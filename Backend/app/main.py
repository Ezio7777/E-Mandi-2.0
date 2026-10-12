"""FastAPI application factory."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app import __version__
from app.api.router import api_router, health_router
from app.core.config import get_settings
from app.core.database import dispose_engine
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.request_id import RequestIDMiddleware, SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    log = get_logger("app")
    app.state.redis = Redis.from_url(s.REDIS_URL, decode_responses=True)
    log.info("startup", environment=s.ENVIRONMENT, demo_mode=s.DEMO_MODE)
    try:
        yield
    finally:
        q = getattr(app.state, "job_queue", None)
        if q is not None:
            await q.close()
        await app.state.redis.aclose()
        await dispose_engine()
        log.info("shutdown")


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging(s.LOG_LEVEL, json_logs=s.ENVIRONMENT != "development")
    app = FastAPI(
        title="E-MANDI 2.0 API", version=__version__, lifespan=lifespan,
        docs_url=None if s.is_production else "/docs",
        redoc_url=None, openapi_url=None if s.is_production else "/openapi.json",
    )
    # Order: last added runs first (outermost). RequestID must wrap everything.
    app.add_middleware(SecurityHeadersMiddleware, hsts=s.is_production)
    app.add_middleware(
        CORSMiddleware, allow_origins=s.cors_origins_list, allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(api_router, prefix=s.API_V1_PREFIX)
    return app


app = create_app()
