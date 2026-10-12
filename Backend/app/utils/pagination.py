"""Opaque keyset-pagination cursors over (created_at, id)."""
import base64
import json
import uuid
from datetime import datetime

from app.core.errors import DomainValidationError


def encode_cursor(ts: datetime, row_id: uuid.UUID) -> str:
    raw = json.dumps({"t": ts.isoformat(), "i": str(row_id)}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        d = json.loads(raw)
        return datetime.fromisoformat(d["t"]), uuid.UUID(d["i"])
    except (ValueError, KeyError, TypeError) as exc:
        raise DomainValidationError("Invalid cursor", details=[{"field": "cursor", "message": "invalid"}]) from exc
