"""Recovery/maintenance jobs (scheduled via arq cron in Stage 18). Each is idempotent and safe to run concurrently."""
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
