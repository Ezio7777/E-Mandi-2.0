import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.database import get_sessionmaker
from app.core.dependencies import CurrentUser, RedisDep, SessionDep, SettingsDep
from app.core.errors import RateLimitError
from app.core.logging import get_logger
from app.core.rate_limit import rate_limit
from app.models.notification import Notification
from app.schemas.common import Envelope
from app.schemas.notification import MarkedRead, NotificationOut, NotificationPage, UnreadCount
from app.services.notification import NotificationService
from app.utils.pagination import decode_cursor, encode_cursor
from app.utils.time import utcnow

log = get_logger(__name__)
router = APIRouter(prefix="/notifications", tags=["notifications"], dependencies=[Depends(rate_limit("notifications", 240, 60, per_user=True))])


def _svc(session: SessionDep) -> NotificationService:
    return NotificationService(session)


Svc = Annotated[NotificationService, Depends(_svc)]


@router.get("", response_model=Envelope[NotificationPage])
async def list_notifications(user: CurrentUser, svc: Svc, unread_only: bool = False, cursor: str | None = Query(None, max_length=300),
                             limit: int = Query(20, ge=1, le=50)):
    rows = await svc.list_for(user.id, unread_only, decode_cursor(cursor) if cursor else None, limit)
    more, rows = len(rows) > limit, rows[:limit]
    return Envelope(data=NotificationPage(items=[NotificationOut.model_validate(r) for r in rows],
                                          next_cursor=encode_cursor(rows[-1].created_at, rows[-1].id) if more else None,
                                          unread_count=await svc.unread_count(user.id)))


@router.get("/unread-count", response_model=Envelope[UnreadCount])
async def unread_count(user: CurrentUser, svc: Svc):
    return Envelope(data=UnreadCount(unread_count=await svc.unread_count(user.id)))


@router.post("/read-all", response_model=Envelope[MarkedRead])
async def read_all(user: CurrentUser, svc: Svc):
    return Envelope(data=MarkedRead(marked=await svc.mark_all_read(user.id)))


def _event(n: Notification) -> str:
    payload = NotificationOut.model_validate(n).model_dump(mode="json")
    return f"id: {n.id}\nevent: notification\ndata: {json.dumps(payload)}\n\n"


async def _acquire_slot(redis: Redis, user_id: uuid.UUID, settings: Settings) -> bool:
    try:
        key = f"sse:{user_id}"
        n = await redis.incr(key)
        await redis.expire(key, settings.SSE_MAX_SECONDS + 30)  # safety net if a worker dies before releasing
        if n > settings.SSE_MAX_CONNECTIONS_PER_USER:
            await redis.decr(key)
            return False
    except Exception as exc:  # noqa: BLE001
        log.warning("sse_cap_unavailable", error=str(exc))  # fail open: availability over the cap
    return True


@router.get("/stream", dependencies=[Depends(rate_limit("sse_connect", 20, 60, per_user=True))])
async def stream(request: Request, user: CurrentUser, settings: SettingsDep, redis: RedisDep,
                 last_event_id: Annotated[str | None, Header(alias="Last-Event-ID", max_length=64)] = None):
    """Server-Sent Events: new notifications for the CURRENT user only. Connections are bounded
    (SSE_MAX_SECONDS) so clients reconnect with Last-Event-ID and nothing is missed. Auth: Authorization header
    (use fetch-based SSE; tokens are never accepted in the URL)."""
    if not await _acquire_slot(redis, user.id, settings):
        raise RateLimitError("Too many open notification streams")
    uid = user.id
    async with get_sessionmaker()() as s:  # resume point: the last event the client saw (must be its OWN notification)
        cursor = (utcnow(), uuid.UUID(int=0))
        if last_event_id:
            try:
                seen = await s.get(Notification, uuid.UUID(last_event_id))
                if seen is not None and seen.user_id == uid:
                    cursor = (seen.created_at, seen.id)
            except ValueError:
                pass

    async def gen() -> AsyncIterator[str]:
        nonlocal cursor
        yield f"retry: {int(settings.SSE_POLL_SECONDS * 1000)}\n\n"
        loop = asyncio.get_running_loop()
        deadline, last_beat = loop.time() + settings.SSE_MAX_SECONDS, loop.time()
        try:
            while loop.time() < deadline and not await request.is_disconnected():
                async with get_sessionmaker()() as s:  # short-lived session per poll: no connection held while idle
                    rows = await NotificationService(s).newer_than(uid, cursor)
                for n in rows:
                    cursor = (n.created_at, n.id)
                    yield _event(n)
                    last_beat = loop.time()
                if loop.time() - last_beat >= 15:
                    yield ": keepalive\n\n"
                    last_beat = loop.time()
                await asyncio.sleep(settings.SSE_POLL_SECONDS)
        finally:
            try:
                await redis.decr(f"sse:{uid}")
            except Exception:  # noqa: BLE001
                pass

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(notification_id: uuid.UUID, user: CurrentUser, svc: Svc) -> None:
    await svc.mark_read(user.id, notification_id)
