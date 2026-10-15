"""Response/request base types. Wire format is camelCase everywhere: every schema derives from CamelModel (aliases are generated, and
requests accept camelCase OR snake_case). Free-form JSON blobs (audit metadata, notification data, ...) are camel-cased by key too, via
CamelBlob; maps whose KEYS are data (counts by status/provider/error code, S3 form fields) are deliberately left untouched."""
import re
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, PlainSerializer
from pydantic.alias_generators import to_camel

T = TypeVar("T")
_SNAKE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$")


def camelize(value: Any) -> Any:
    """Recursively camel-case snake_case dict KEYS (single words, UPPER_CASE and Capitalised keys are left alone)."""
    if isinstance(value, dict):
        return {(to_camel(k) if isinstance(k, str) and _SNAKE.match(k) else k): camelize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [camelize(v) for v in value]
    return value


_blob = PlainSerializer(camelize, return_type=Any, when_used="json")
CamelBlob = Annotated[dict[str, Any], _blob]
CamelBlobList = Annotated[list[dict[str, Any]], _blob]


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Envelope(CamelModel, Generic[T]):
    data: T
    meta: dict[str, Any] | None = None


class Page(CamelModel):
    next_cursor: str | None = None
    limit: int


def ok(data: Any, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"data": data, "meta": camelize(meta) if meta else meta}
