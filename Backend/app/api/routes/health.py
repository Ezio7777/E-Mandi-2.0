"""Liveness and readiness probes."""
import time

from fastapi import APIRouter, Request, Response
from sqlalchemy import text

from app.core.database import get_sessionmaker

router = APIRouter(prefix="/health", tags=["health"])
WORKER_HEARTBEAT_KEY = "worker:heartbeat"
WORKER_STALE_AFTER_SECONDS = 90


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request, response: Response) -> dict:
    checks: dict[str, str] = {}
    try:
        async with get_sessionmaker()() as s:
            await s.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001
        checks["database"] = "fail"
    try:
        redis = request.app.state.redis
        await redis.ping()
        checks["redis"] = "ok"
        beat = await redis.get(WORKER_HEARTBEAT_KEY)
        if beat is None:
            checks["worker"] = "no_heartbeat"
        else:
            checks["worker"] = "ok" if time.time() - float(beat) < WORKER_STALE_AFTER_SECONDS else "stale"
    except Exception:  # noqa: BLE001
        checks["redis"] = "fail"
        checks["worker"] = "unknown"
    # Worker is reported but only DB + Redis gate readiness (API can serve without the worker).
    healthy = checks["database"] == "ok" and checks["redis"] == "ok"
    if not healthy:
        response.status_code = 503
    return {"status": "ready" if healthy else "degraded", "checks": checks}
