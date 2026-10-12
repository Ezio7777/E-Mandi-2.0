"""Redis sliding-window rate limiting exposed as a FastAPI dependency factory."""
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request
from redis.asyncio import Redis

from app.core.errors import AppError, RateLimitError
from app.core.logging import get_logger
from app.core.security import decode_access_token

log = get_logger(__name__)


async def check_rate_limit(redis: Redis, key: str, limit: int, window: int) -> tuple[bool, int]:
    """Returns (allowed, retry_after_seconds)."""
    now = time.time()
    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, now - window)
    pipe.zadd(key, {f"{now}:{uuid.uuid4().hex}": now})
    pipe.zcard(key)
    pipe.zrange(key, 0, 0, withscores=True)
    pipe.expire(key, window + 1)
    _, _, count, oldest, _ = await pipe.execute()
    if count <= limit:
        return True, 0
    retry = int(window - (now - oldest[0][1])) + 1 if oldest else window
    return False, max(retry, 1)


def client_ip(request: Request) -> str:
    # Caddy sets X-Forwarded-For; only its LAST hop is trusted (proxy-appended).
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(name: str, limit: int, window_seconds: int, *, per_user: bool = False,
               fail_open: bool = True) -> Callable[[Request], Awaitable[None]]:
    async def _dep(request: Request) -> None:
        redis: Redis | None = getattr(request.app.state, "redis", None)
        if redis is None:
            return
        ident = client_ip(request)
        if per_user:
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                try:
                    ident = f"u:{decode_access_token(auth[7:]).user_id}"
                except AppError:
                    pass  # invalid token: fall back to IP; auth dependency will reject the request anyway
        try:
            ok, retry = await check_rate_limit(redis, f"rl:{name}:{ident}", limit, window_seconds)
        except Exception as exc:  # noqa: BLE001
            log.warning("rate_limit_backend_error", name=name, error=str(exc))
            if fail_open:
                return
            raise RateLimitError("Rate limiter unavailable, try again shortly") from exc
        if not ok:
            raise RateLimitError(headers={"Retry-After": str(retry)})

    return _dep
