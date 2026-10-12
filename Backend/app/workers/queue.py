"""Job queue abstraction over arq (Redis). Enqueue only AFTER the DB transaction commits."""
from typing import Any, Protocol

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import Settings


class JobQueue(Protocol):
    async def enqueue(self, name: str, *args: Any, defer_seconds: float | None = None) -> None: ...


class ArqJobQueue:
    def __init__(self, settings: Settings) -> None:
        self._rs = RedisSettings.from_dsn(settings.REDIS_URL)
        self._pool: ArqRedis | None = None

    async def enqueue(self, name: str, *args: Any, defer_seconds: float | None = None) -> None:
        if self._pool is None:
            self._pool = await create_pool(self._rs)
        await self._pool.enqueue_job(name, *args, _defer_by=defer_seconds)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()


class RecordingJobQueue:
    """Test/dev double: records jobs instead of executing them."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple]] = []

    async def enqueue(self, name: str, *args: Any, defer_seconds: float | None = None) -> None:
        self.jobs.append((name, args))
