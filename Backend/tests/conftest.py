"""Global test environment. Forces an isolated DB/Redis so tests can never touch dev data."""
import os

os.environ.update({
    "ENVIRONMENT": "test",
    "DEMO_MODE": "true",
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL",
                                   "postgresql+asyncpg://postgres:postgres@localhost:5433/emandi_test"),
    "REDIS_URL": os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/1"),
    "JWT_SECRET": "test-secret-test-secret-test-secret-0123456789",
    "GOOGLE_CLIENT_ID": "test-client-id.apps.googleusercontent.com",
    "LOG_LEVEL": "WARNING",
    "PAYMENT_PROVIDER": "mock",
    "PAYMENT_KEY_ID": "rzp_test_mockkey",
    "PAYMENT_WEBHOOK_SECRET": "test-webhook-secret-0123456789",
})


# ---------------------------------------------------------------------------------------------------------------
# Wire format is camelCase (Stage 24). The pre-existing behavioural tests were written against snake_case keys, so
# `Response.json()` returns the body with keys converted back to snake_case; this keeps those assertions meaningful
# without touching hundreds of lines. The REAL wire format is asserted by tests/integration/test_wire_format.py, which
# uses `wire(response)` (the untouched body).
# ---------------------------------------------------------------------------------------------------------------
import json as _json
import re as _re

import httpx

_CAMEL = _re.compile(r"^[a-z][a-z0-9]*([A-Z][a-z0-9]*)+$")


def _snake_key(k: str) -> str:
    if not _CAMEL.match(k):
        return k
    return _re.sub(r"(?<=[a-z0-9])([A-Z])", lambda m: "_" + m.group(1).lower(), k)


def snakeize(v):
    if isinstance(v, dict):
        return {_snake_key(k) if isinstance(k, str) else k: snakeize(x) for k, x in v.items()}
    if isinstance(v, list):
        return [snakeize(x) for x in v]
    return v


def wire(response: httpx.Response):
    """The body exactly as sent over the wire (camelCase)."""
    return _json.loads(response.content)


_orig_json = httpx.Response.json


def _json_snake(self: httpx.Response, **kw):
    return snakeize(_orig_json(self, **kw))


httpx.Response.json = _json_snake  # type: ignore[method-assign]
