"""Domain errors + global exception handlers producing the standard error envelope."""
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

log = get_logger(__name__)


class AppError(Exception):
    status_code = 400
    code = "bad_request"
    message = "Bad request"

    def __init__(self, message: str | None = None, *, details: list[dict[str, Any]] | None = None,
                 headers: dict[str, str] | None = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.details = details or []
        self.headers = headers


class UnauthorizedError(AppError):
    status_code, code, message = 401, "unauthorized", "Authentication required"


class ForbiddenError(AppError):
    status_code, code, message = 403, "forbidden", "You do not have access to this resource"


class NotFoundError(AppError):
    status_code, code, message = 404, "not_found", "Resource not found"


class ConflictError(AppError):
    status_code, code, message = 409, "conflict", "Request conflicts with current state"


class InvalidTransitionError(ConflictError):
    code, message = "invalid_state_transition", "Invalid state transition"


class InsufficientStockError(ConflictError):
    code, message = "insufficient_stock", "Requested quantity is not available"


class DomainValidationError(AppError):
    status_code, code, message = 422, "validation_error", "Validation failed"


class RateLimitError(AppError):
    status_code, code, message = 429, "rate_limited", "Too many requests"


class ProviderError(AppError):
    status_code, code, message = 502, "provider_error", "Upstream provider failed"


def _envelope(request: Request, code: str, message: str, details: list[dict[str, Any]] | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or [],
                      "requestId": getattr(request.state, "request_id", None)}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(_envelope(request, exc.code, exc.message, exc.details),
                            status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]}
                   for e in exc.errors()]
        return JSONResponse(_envelope(request, "validation_error", "Request validation failed", details),
                            status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(_envelope(request, code, str(exc.detail)), status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_exception", path=request.url.path, exc_info=exc)
        return JSONResponse(_envelope(request, "internal_error", "An unexpected error occurred"),
                            status_code=500)
