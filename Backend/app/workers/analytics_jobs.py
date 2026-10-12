"""arq job: precompute the admin analytics overview into the Redis cache (scheduled as a cron in the worker settings)."""
from typing import Any

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.core.logging import get_logger
from app.services.analytics import AnalyticsService

log = get_logger(__name__)
WINDOWS = (7, 30, 90)


async def refresh_analytics_job(ctx: dict[str, Any]) -> int:
    settings = get_settings()
    redis = ctx.get("redis_client") or Redis.from_url(settings.REDIS_URL, decode_responses=True)
    n = 0
    try:
        async with get_sessionmaker()() as session:
            svc = AnalyticsService(session, settings, redis)
            for days in WINDOWS:
                await svc.store(await svc.compute_overview(days))
                n += 1
    finally:
        if ctx.get("redis_client") is None:
            await redis.aclose()
    log.info("analytics_refreshed", windows=n)
    return n
