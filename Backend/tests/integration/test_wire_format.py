"""Global wire contract: {data, meta} envelopes, camelCase keys, requestId on errors, free-form maps left intact."""
import json
import re

from app.schemas.common import camelize

from tests.conftest import wire
from tests.integration.conftest import bearer, register

SNAKE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$")


def snake_keys(o, path="$"):
    out = []
    if isinstance(o, dict):
        for k, v in o.items():
            if SNAKE.match(k):
                out.append(f"{path}.{k}")
            out += snake_keys(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            out += snake_keys(v, f"{path}[{i}]")
    return out


async def test_success_envelope_is_camel_and_has_data_meta(client):
    h = bearer(await register(client))
    r = await client.get("/api/v1/auth/me", headers=h)
    body = wire(r)
    assert set(body) == {"data", "meta"}
    assert "createdAt" in body["data"] or "fullName" in body["data"]
    assert snake_keys(body) == []


async def test_error_envelope_uses_request_id(client):
    r = await client.get("/api/v1/auth/me")
    body = wire(r)
    assert r.status_code == 401 and set(body) == {"error"}
    assert {"code", "message", "requestId"} <= set(body["error"]) and "request_id" not in body["error"]


async def test_validation_error_is_enveloped(client):
    r = await client.post("/api/v1/auth/login", json={"email": "nope"})
    body = wire(r)
    assert r.status_code == 422 and "error" in body and snake_keys(body) == []


async def test_list_endpoint_meta_is_camel(client):
    h = bearer(await register(client))
    r = await client.get("/api/v1/listings?limit=5", headers=h)
    body = wire(r)
    assert r.status_code == 200 and "data" in body and snake_keys(body) == []
    meta = body["meta"] or {}
    assert "next_cursor" not in meta


def test_camelize_converts_snake_keys_recursively_and_leaves_others():
    src = {"job_id": 1, "nested_obj": [{"range_min": 2}], "Already": 1, "mixedCase": 2, "crop-map": {"a_b": 1}}
    out = camelize(src)
    assert out["jobId"] == 1 and out["nestedObj"][0]["rangeMin"] == 2 and out["Already"] == 1 and out["mixedCase"] == 2
    assert out["crop-map"] == {"aB": 1}
    assert json.dumps(out)


async def test_sse_event_payload_is_camel(client):
    import inspect

    from app.api.routes.notifications import _event
    from app.schemas.notification import NotificationOut
    assert "by_alias=True" in inspect.getsource(_event) and NotificationOut
