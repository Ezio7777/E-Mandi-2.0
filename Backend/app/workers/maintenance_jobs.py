"""Recovery/maintenance jobs (scheduled via arq cron in Stage 18). Each is idempotent and safe to run concurrently."""
import time
from typing import Any

from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.core.logging import get_logger
from app.services.order import OrderService

log = get_logger(__name__)


async def expire_reservations_job(ctx: dict[str, Any]) -> int:
    """Cancels unpaid orders past their reservation window and releases the held stock."""
    settings = ctx.get("settings") or get_settings()
    total = 0
    async with get_sessionmaker()() as session:
        svc = OrderService(session, settings)
        while True:
            n = await svc.expire_reservations(100)
            total += n
            if n < 100:
                break
    if total:
        log.info("reservations_expired", count=total)
    return total


# ---------------------------------------------------------------------------------------------
# Stage 18: recovery sweepers + heartbeat (scheduled by WorkerSettings.cron_jobs)
# ---------------------------------------------------------------------------------------------
from redis.asyncio import Redis  # noqa: E402

from app.integrations.aws.s3 import S3Storage  # noqa: E402
from app.services.recovery import HEARTBEAT_KEY, RecoveryService  # noqa: E402
from app.workers.queue import ArqJobQueue  # noqa: E402

SWEEPERS = {
    "executions": "recover_executions",
    "analyzing": "recover_analyzing",
    "webhooks": "reprocess_webhooks",
    "cleanup": "cleanup_expired",
    "orphan_images": "sweep_orphan_images",
    "rematch": "rematch_requirements",
    "interrupted_actions": "fail_interrupted_actions",
}


async def run_sweeper(ctx: dict[str, Any], name: str) -> dict[str, Any]:
    """Runs one named sweeper; never raises (a failing sweeper must not poison the cron loop) and records its outcome."""
    settings = ctx.get("settings") or get_settings()
    own_redis = ctx.get("redis_client") is None
    redis = ctx.get("redis_client") or Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        svc = RecoveryService(get_sessionmaker(), settings, ctx.get("queue") or ArqJobQueue(settings), redis,
                              ctx.get("storage") or (S3Storage(settings) if name == "orphan_images" else None), ctx.get("payment_provider"))
        try:
            result = await getattr(svc, SWEEPERS[name])()
        except Exception as exc:
            log.error("sweeper_failed", sweeper=name, error_type=type(exc).__name__)
            await svc.record(name, None, type(exc).__name__)
            return {"error": type(exc).__name__}
        await svc.record(name, result)
        if any(result.values()):
            log.info("sweeper_done", sweeper=name, **result)
        return result
    finally:
        if own_redis:
            await redis.aclose()


async def recover_executions_job(ctx: dict[str, Any]) -> dict[str, Any]:
    return await run_sweeper(ctx, "executions")


async def recover_analyzing_job(ctx: dict[str, Any]) -> dict[str, Any]:
    return await run_sweeper(ctx, "analyzing")


async def reprocess_webhooks_job(ctx: dict[str, Any]) -> dict[str, Any]:
    return await run_sweeper(ctx, "webhooks")


async def cleanup_expired_job(ctx: dict[str, Any]) -> dict[str, Any]:
    return await run_sweeper(ctx, "cleanup")


async def sweep_orphan_images_job(ctx: dict[str, Any]) -> dict[str, Any]:
    return await run_sweeper(ctx, "orphan_images")


async def rematch_requirements_job(ctx: dict[str, Any]) -> dict[str, Any]:
    return await run_sweeper(ctx, "rematch")


async def fail_interrupted_actions_job(ctx: dict[str, Any]) -> dict[str, Any]:
    return await run_sweeper(ctx, "interrupted_actions")


async def worker_heartbeat_job(ctx: dict[str, Any]) -> None:
    settings = ctx.get("settings") or get_settings()
    redis = ctx.get("redis_client") or Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await redis.set(HEARTBEAT_KEY, f"{time.time():.3f}", ex=600)  # epoch seconds: /health/ready parses it as a float
    finally:
        if ctx.get("redis_client") is None:
            await redis.aclose()
