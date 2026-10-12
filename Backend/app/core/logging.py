"""Structured logging (structlog) with request-id binding and secret redaction."""
import logging
import sys
from typing import Any

import structlog

_SENSITIVE = (
    "password", "secret", "token", "authorization", "api_key", "apikey",
    "credential", "cookie", "otp", "signature",
)


def _redact(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key in list(event_dict):
        if any(s in key.lower() for s in _SENSITIVE):
            event_dict[key] = "***REDACTED***"
    return event_dict


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer(),
    ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=level.upper(), stream=sys.stdout, format="%(message)s")


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name)
