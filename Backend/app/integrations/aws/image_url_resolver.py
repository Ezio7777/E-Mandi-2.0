"""Turns stored S3 keys into client-fetchable URLs. Swap the implementation to move to CloudFront."""
from typing import Protocol

from app.core.config import Settings
from app.integrations.aws.s3 import ObjectStorage


class ImageUrlResolver(Protocol):
    async def url_for(self, key: str) -> str: ...


class PresignedUrlResolver:
    """Private bucket: short-lived presigned GET URLs."""

    def __init__(self, storage: ObjectStorage, expires: int) -> None:
        self.storage, self.expires = storage, expires

    async def url_for(self, key: str) -> str:
        return await self.storage.presign_get(key, self.expires)


class PublicBaseUrlResolver:
    """CloudFront (or other CDN) in front of the bucket: stable URL, no per-request signing.
    For private CloudFront distributions, add a CloudFrontSignedUrlResolver with the same interface."""

    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/")

    async def url_for(self, key: str) -> str:
        return f"{self.base}/{key}"


def build_resolver(settings: Settings, storage: ObjectStorage) -> ImageUrlResolver:
    if settings.AWS_S3_PUBLIC_BASE_URL:
        return PublicBaseUrlResolver(settings.AWS_S3_PUBLIC_BASE_URL)
    return PresignedUrlResolver(storage, settings.S3_READ_URL_EXPIRE_SECONDS)
