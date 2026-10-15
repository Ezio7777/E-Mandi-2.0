"""Pure-ASGI request body cap. Caddy already caps bodies in production; this is the app-level backstop (direct access, other proxies,
chunked uploads without Content-Length). Responds 413 in the standard error envelope."""
import json
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class _TooLarge(Exception):
    pass


def _has_too_large(exc: BaseException) -> bool:
    if isinstance(exc, _TooLarge):
        return True
    return any(_has_too_large(e) for e in getattr(exc, "exceptions", ()))


class MaxBodySizeMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope.get("headers") or []).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(send)
            return
        received, started = 0, False

        async def counting_receive() -> Message:
            nonlocal received
            msg = await receive()
            if msg["type"] == "http.request":
                received += len(msg.get("body", b""))
                if received > self.max_bytes:
                    raise _TooLarge
            return msg

        async def tracking_send(msg: Message) -> None:
            nonlocal started
            if msg["type"] == "http.response.start":
                started = True
            await send(msg)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except BaseException as exc:
            if _has_too_large(exc) and not started:
                await self._reject(send)
                return
            raise

    async def _reject(self, send: Send) -> None:
        body: dict[str, Any] = {"error": {"code": "payload_too_large", "message": "Request body is too large", "details": [], "requestId": None}}
        raw = json.dumps(body).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode()), (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": raw})
