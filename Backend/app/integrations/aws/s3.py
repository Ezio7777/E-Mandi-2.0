"""Object storage abstraction. S3 is the permanent store; Postgres only holds keys + metadata."""
import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import Settings
from app.core.errors import ProviderError
from app.core.logging import get_logger

log = get_logger(__name__)
SSE = {"x-amz-server-side-encryption": "AES256"}


@dataclass(frozen=True)
class PresignedPost:
    url: str
    fields: dict[str, str]


@dataclass(frozen=True)
class ObjectHead:
    size: int
    content_type: str | None


class ObjectStorage(Protocol):
    async def presign_post(self, key: str, content_type: str, max_bytes: int, expires: int) -> PresignedPost: ...
    async def presign_get(self, key: str, expires: int) -> str: ...
    async def head(self, key: str) -> ObjectHead | None: ...
    async def get_bytes(self, key: str, max_bytes: int) -> bytes: ...
    async def delete(self, key: str) -> None: ...
    async def list_keys(self, prefix: str, limit: int) -> list[tuple[str, datetime]]: ...


class S3Storage:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.bucket = settings.AWS_S3_BUCKET
        if client is None:
            kw: dict[str, Any] = {"region_name": settings.AWS_REGION, "config": Config(signature_version="s3v4")}
            if settings.S3_ENDPOINT_URL:
                kw["endpoint_url"] = settings.S3_ENDPOINT_URL
            if settings.AWS_ACCESS_KEY_ID:  # empty => default chain (EC2 instance role in production)
                kw["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
                kw["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY.get_secret_value()
            client = boto3.client("s3", **kw)
        self.client = client

    async def _run(self, fn, *a, **kw):
        try:
            return await asyncio.to_thread(fn, *a, **kw)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"404", "NoSuchKey", "NotFound"}:
                raise FileNotFoundError from exc
            log.error("s3_error", code=code, op=getattr(fn, "__name__", "?"))
            raise ProviderError("Storage service error") from exc

    async def presign_post(self, key: str, content_type: str, max_bytes: int, expires: int) -> PresignedPost:
        conditions: list[Any] = [{"Content-Type": content_type}, SSE, ["content-length-range", 1, max_bytes]]
        r = await self._run(self.client.generate_presigned_post, self.bucket, key,
                            Fields={"Content-Type": content_type, **SSE}, Conditions=conditions, ExpiresIn=expires)
        return PresignedPost(url=r["url"], fields=r["fields"])

    async def presign_get(self, key: str, expires: int) -> str:
        return await self._run(self.client.generate_presigned_url, "get_object",
                               Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires)

    async def head(self, key: str) -> ObjectHead | None:
        try:
            r = await self._run(self.client.head_object, Bucket=self.bucket, Key=key)
        except FileNotFoundError:
            return None
        return ObjectHead(size=int(r["ContentLength"]), content_type=r.get("ContentType"))

    async def get_bytes(self, key: str, max_bytes: int) -> bytes:
        def _get() -> bytes:
            body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
            data = body.read(max_bytes + 1)  # never read more than the cap
            body.close()
            return data
        data = await self._run(_get)
        if len(data) > max_bytes:
            raise ProviderError("Object exceeds allowed size")
        return data

    async def delete(self, key: str) -> None:
        try:
            await self._run(self.client.delete_object, Bucket=self.bucket, Key=key)
        except ProviderError:
            log.warning("s3_delete_failed", key=key)  # best-effort; orphan sweeper cleans up

    async def list_keys(self, prefix: str, limit: int) -> list[tuple[str, datetime]]:
        """(key, last_modified) for up to `limit` objects under prefix (used by the orphan sweeper)."""
        def _list() -> list[tuple[str, datetime]]:
            out: list[tuple[str, datetime]] = []
            for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
                for o in page.get("Contents", []):
                    out.append((o["Key"], o["LastModified"]))
                    if len(out) >= limit:
                        return out
            return out
        return await self._run(_list)
