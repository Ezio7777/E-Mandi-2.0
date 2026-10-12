from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: dict[str, Any] | None = None


class Page(BaseModel):
    next_cursor: str | None = None
    limit: int


def ok(data: Any, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"data": data, "meta": meta}
