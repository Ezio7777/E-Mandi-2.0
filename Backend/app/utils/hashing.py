import hashlib
import json
from typing import Any


def sha256_hex(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def canonical_hash(obj: Any) -> str:
    return sha256_hex(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str))
