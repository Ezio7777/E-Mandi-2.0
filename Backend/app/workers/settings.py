"""arq WorkerSettings: `arq app.workers.settings.WorkerSettings`. One always-on worker process runs every agent job and
the cron sweepers. Shared clients are built once in on_startup and reused via ctx."""
from typing import Any

from arq import cron
from arq.connections import RedisSettings
from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.integrations.aws.s3 import S3Storage
from app.integrations.gemini.text import GeminiTextLLM
from app.integrations.openai.text import OpenAITextLLM
from app.services.embedding import build_embedding_provider
from app.services.grading import build_graders
from app.workers.analytics_jobs import refresh_analytics_job
from app.workers.embedding_jobs import embed_market_reports_job
from app.workers.grading_jobs import grade_listing_job
from app.workers.maintenance_jobs import (
    cleanup_expired_job,
    expire_reservations_job,
    fail_interrupted_actions_job,
    recover_analyzing_job,
    recover_executions_job,
    rematch_requirements_job,
    reprocess_webhooks_job,
    sweep_orphan_images_job,
    worker_heartbeat_job,
)
from app.workers.matching_jobs import match_requirement_job
from app.workers.pricing_jobs import price_listing_job
from app.workers.queue import ArqJobQueue
from app.workers.risk_jobs import assess_risk_job

log = get_logger(__name__)
_settings = get_settings()


async def on_startup(ctx: dict[str, Any]) -> None:
    s = get_settings()
    configure_logging(s.LOG_LEVEL, json_logs=s.ENVIRONMENT != "development")
    ctx["settings"] = s
    ctx["storage"] = S3Storage(s)
    ctx["embedder"] = build_embedding_provider(s)
    ctx["graders"] = build_graders(s)
    ctx["llms"] = [GeminiTextLLM(s), OpenAITextLLM(s)]
    ctx["queue"] = ArqJobQueue(s)
    ctx["redis_client"] = Redis.from_url(s.REDIS_URL, decode_responses=True)
    log.info("worker_started")


async def on_shutdown(ctx: dict[str, Any]) -> None:
    if ctx.get("queue") is not None:
        await ctx["queue"].close()
    if ctx.get("redis_client") is not None:
        await ctx["redis_client"].aclose()
    log.info("worker_stopped")


class WorkerSettings:
    functions = [grade_listing_job, price_listing_job, match_requirement_job, assess_risk_job, embed_market_reports_job,
                 expire_reservations_job, refresh_analytics_job, recover_executions_job, recover_analyzing_job,
                 reprocess_webhooks_job, cleanup_expired_job, sweep_orphan_images_job, rematch_requirements_job,
                 fail_interrupted_actions_job, worker_heartbeat_job]
    cron_jobs = [
        cron(worker_heartbeat_job, minute=set(range(60)), run_at_startup=True, unique=True),
        cron(expire_reservations_job, minute=set(range(60)), unique=True),
        cron(recover_executions_job, minute={1, 6, 11, 16, 21, 26, 31, 36, 41, 46, 51, 56}, unique=True),
        cron(recover_analyzing_job, minute={2, 12, 22, 32, 42, 52}, unique=True),
        cron(reprocess_webhooks_job, minute={3, 8, 13, 18, 23, 28, 33, 38, 43, 48, 53, 58}, unique=True),
        cron(fail_interrupted_actions_job, minute={4, 14, 24, 34, 44, 54}, unique=True),
        cron(rematch_requirements_job, minute={5, 35}, unique=True),
        cron(refresh_analytics_job, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}, unique=True),
        cron(embed_market_reports_job, hour={2}, minute={30}, unique=True),
        cron(cleanup_expired_job, hour={3}, minute={10}, unique=True),
        cron(sweep_orphan_images_job, hour={3}, minute={40}, unique=True),
    ]
    on_startup = staticmethod(on_startup)
    on_shutdown = staticmethod(on_shutdown)
    redis_settings = RedisSettings.from_dsn(_settings.REDIS_URL)
    max_tries = 3
    job_timeout = 300
    keep_result = 3600
    max_jobs = 10
    health_check_interval = 30
    health_check_key = "worker:arq-health"
