"""Image upload lifecycle: init (presigned POST) -> direct-to-S3 upload -> confirm (server-side validation).

Security properties:
- S3 keys are server-generated (UUID); client filenames are never trusted or stored.
- Presigned POST enforces content-type + size range at S3; confirm re-validates size, magic bytes,
  Pillow parse, dimensions and declared-vs-actual type. Invalid objects are deleted immediately.
- Upload grants are signed, short-lived, bound to (user, listing, key).
"""
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import transactional
from app.core.errors import AppError, ConflictError, DomainValidationError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.core.security import sign_token, verify_signed_token
from app.integrations.aws.image_url_resolver import ImageUrlResolver
from app.integrations.aws.s3 import ObjectStorage
from app.models.enums import ListingStatus
from app.models.listing_image import ListingImage
from app.models.user import User
from app.models.user_profile import UserProfile
from app.repositories.image import ImageRepository
from app.repositories.listing import ListingRepository
from app.schemas.image import (
    AvatarOut, ImageOut, ProfileUploadInitRequest, UploadInitRequest, UploadInitResponse,
)
from app.services.access import assert_can_view_listing, assert_owner_listing
from app.services.audit import Actor, AuditService, RequestContext
from app.utils.hashing import sha256_hex
from app.utils.images import ImageInfo, InvalidImage, ext_for, sniff_image

log = get_logger(__name__)
KEY_ROOT = "e-mandi"
_EXTS = {"image/jpeg": {"jpg", "jpeg"}, "image/png": {"png"}, "image/webp": {"webp"}}
UPLOADABLE = {ListingStatus.DRAFT, ListingStatus.ACTIVE, ListingStatus.REVIEW_REQUIRED}
UPLOAD_TOKEN_TTL = 900


@dataclass(frozen=True)
class ConfirmedImage:
    image: ListingImage
    is_new: bool  # False when confirm was replayed (idempotent)


class ImageService:
    def __init__(self, session: AsyncSession, settings: Settings, storage: ObjectStorage,
                 resolver: ImageUrlResolver) -> None:
        self.session, self.settings, self.storage, self.resolver = session, settings, storage, resolver
        self.images, self.listings = ImageRepository(session), ListingRepository(session)
        self.audit = AuditService(session)

    # ---------- validation helpers ----------
    def _validate_declared(self, filename: str, content_type: str, size: int) -> None:
        try:
            ext_for(content_type)
        except InvalidImage as exc:
            raise DomainValidationError(str(exc), details=[{"field": "content_type", "message": str(exc)}]) from exc
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in _EXTS[content_type]:
            raise DomainValidationError("File extension does not match content type",
                                        details=[{"field": "filename", "message": "extension/content-type mismatch"}])
        if size > self.settings.IMAGE_MAX_BYTES:
            raise DomainValidationError(
                f"File too large (max {self.settings.IMAGE_MAX_BYTES // (1024 * 1024)} MB)",
                details=[{"field": "size_bytes", "message": "too large"}])

    async def _presign(self, key: str, content_type: str, payload: dict) -> UploadInitResponse:
        s = self.settings
        post = await self.storage.presign_post(key, content_type, s.IMAGE_MAX_BYTES, s.S3_PRESIGN_EXPIRE_SECONDS)
        token = sign_token({**payload, "key": key, "ct": content_type}, typ="upload", ttl_seconds=UPLOAD_TOKEN_TTL,
                           settings=s)
        return UploadInitResponse(upload_token=token, url=post.url, fields=post.fields, object_key=key,
                                  expires_in=s.S3_PRESIGN_EXPIRE_SECONDS, max_bytes=s.IMAGE_MAX_BYTES)

    async def _fetch_validated(self, key: str, declared_ct: str) -> tuple[bytes, ImageInfo]:
        """Download + validate. On ANY failure the object is deleted so unvalidated files never linger."""
        s = self.settings
        try:
            head = await self.storage.head(key)
            if head is None:
                raise DomainValidationError("Upload not found - please upload the file first")
            if head.size <= 0 or head.size > s.IMAGE_MAX_BYTES:
                raise DomainValidationError("File size is not allowed")
            data = await self.storage.get_bytes(key, s.IMAGE_MAX_BYTES)
            try:
                info = sniff_image(data, min_dim=s.IMAGE_MIN_DIMENSION, max_dim=s.IMAGE_MAX_DIMENSION)
            except InvalidImage as exc:
                raise DomainValidationError(str(exc)) from exc
            if info.content_type != declared_ct:
                raise DomainValidationError("Uploaded file type does not match the declared type")
            return data, info
        except AppError:
            await self.storage.delete(key)
            raise

    def _claims(self, token: str, user: User, purpose: str) -> dict:
        c = verify_signed_token(token, typ="upload", settings=self.settings)
        if c.get("uid") != str(user.id) or c.get("purpose") != purpose:
            raise ForbiddenError("This upload grant does not belong to you")
        return c

    async def to_out(self, img: ListingImage) -> ImageOut:
        return ImageOut(id=img.id, listing_id=img.listing_id, url=await self.resolver.url_for(img.s3_key),
                        content_type=img.content_type, size_bytes=img.size_bytes, width=img.width,
                        height=img.height, is_primary=img.is_primary, created_at=img.created_at)

    # ---------- listing images ----------
    async def init_listing_upload(self, user: User, req: UploadInitRequest) -> UploadInitResponse:
        self._validate_declared(req.filename, req.content_type, req.size_bytes)
        listing = assert_owner_listing(user, await self.listings.get(req.listing_id))
        if listing.status not in UPLOADABLE:
            raise ConflictError(f"Images cannot be changed while the listing is {listing.status.value}")
        count = await self.images.count_for_listing(listing.id)
        if req.replace_image_id is None and count >= self.settings.IMAGE_MAX_COUNT_PER_LISTING:
            raise ConflictError(f"A listing can have at most {self.settings.IMAGE_MAX_COUNT_PER_LISTING} images")
        if req.replace_image_id is not None:
            old = await self.images.get(req.replace_image_id)
            if old is None or old.listing_id != listing.id:
                raise NotFoundError("Image not found")
        key = f"{KEY_ROOT}/listings/{listing.id}/{uuid.uuid4()}.{ext_for(req.content_type)}"
        return await self._presign(key, req.content_type, {
            "purpose": "listing_image", "uid": str(user.id), "lid": str(listing.id),
            "rep": str(req.replace_image_id) if req.replace_image_id else None})

    async def confirm_listing_upload(self, user: User, token: str, ctx: RequestContext) -> ConfirmedImage:
        c = self._claims(token, user, "listing_image")
        key, listing_id = c["key"], uuid.UUID(c["lid"])
        existing = await self.images.get_by_key(key)
        if existing is not None:  # idempotent replay of a successful confirm
            return ConfirmedImage(existing, False)
        data, info = await self._fetch_validated(key, c["ct"])
        replaced_key: str | None = None
        try:
            async with transactional(self.session):
                listing = await self.listings.get_for_update(listing_id)
                assert_owner_listing(user, listing)
                assert listing is not None
                if listing.status not in UPLOADABLE:
                    raise ConflictError(f"Images cannot be changed while the listing is {listing.status.value}")
                old: ListingImage | None = None
                if c.get("rep"):
                    old = await self.images.get(uuid.UUID(c["rep"]))
                    if old is None or old.listing_id != listing.id:
                        raise NotFoundError("Image to replace was not found")
                count = await self.images.count_for_listing(listing.id)
                if count - (1 if old else 0) >= self.settings.IMAGE_MAX_COUNT_PER_LISTING:
                    raise ConflictError("Image limit reached for this listing")
                make_primary = count == 0 or bool(old and old.is_primary)
                if old:
                    replaced_key = old.s3_key
                    await self.images.delete(old)  # flush first: frees the single-primary unique slot
                img = await self.images.add(ListingImage(
                    listing_id=listing.id, s3_key=key, content_type=info.content_type, size_bytes=len(data),
                    width=info.width, height=info.height, sha256=sha256_hex(data), is_primary=make_primary))
                self.audit.record(
                    action="image.replaced" if old else "image.uploaded", entity_type="listing_image",
                    entity_id=img.id, actor=Actor(user.id, user.role), ip=ctx.ip,
                    metadata={"listing_id": str(listing.id), "size_bytes": len(data), "sha256": img.sha256},
                    previous_state={"image_id": str(old.id), "s3_key": old.s3_key} if old else None,
                    new_state={"image_id": str(img.id), "is_primary": img.is_primary})
        except AppError:
            await self.storage.delete(key)
            raise
        if replaced_key:
            await self.storage.delete(replaced_key)
        return ConfirmedImage(img, True)

    async def list_for_listing(self, user: User, listing_id: uuid.UUID) -> list[ImageOut]:
        assert_can_view_listing(user, await self.listings.get(listing_id))
        return [await self.to_out(i) for i in await self.images.list_for_listing(listing_id)]

    async def set_primary(self, user: User, image_id: uuid.UUID, ctx: RequestContext) -> ListingImage:
        async with transactional(self.session):
            img = await self.images.get(image_id)
            if img is None:
                raise NotFoundError("Image not found")
            listing = await self.listings.get_for_update(img.listing_id)
            assert_owner_listing(user, listing)
            for other in await self.images.list_for_listing(img.listing_id):
                if other.is_primary and other.id != img.id:
                    other.is_primary = False
            await self.session.flush()
            img.is_primary = True
            self.audit.record(action="image.primary_changed", entity_type="listing_image", entity_id=img.id,
                              actor=Actor(user.id, user.role), ip=ctx.ip, metadata={"listing_id": str(img.listing_id)})
        return img

    async def delete_image(self, user: User, image_id: uuid.UUID, ctx: RequestContext) -> None:
        key: str
        async with transactional(self.session):
            img = await self.images.get(image_id)
            if img is None:
                raise NotFoundError("Image not found")
            listing = await self.listings.get_for_update(img.listing_id)
            assert_owner_listing(user, listing, allow_admin=True)
            assert listing is not None
            if listing.status not in UPLOADABLE:
                raise ConflictError(f"Images cannot be changed while the listing is {listing.status.value}")
            siblings = [i for i in await self.images.list_for_listing(listing.id) if i.id != img.id]
            if listing.status == ListingStatus.ACTIVE and not siblings:
                raise ConflictError("An active listing must keep at least one image")
            key, was_primary = img.s3_key, img.is_primary
            await self.images.delete(img)
            if was_primary and siblings:
                siblings[0].is_primary = True
            self.audit.record(action="image.deleted", entity_type="listing_image", entity_id=image_id,
                              actor=Actor(user.id, user.role), ip=ctx.ip, metadata={"listing_id": str(listing.id)},
                              previous_state={"s3_key": key, "is_primary": was_primary})
        await self.storage.delete(key)

    # ---------- profile avatar ----------
    async def init_profile_upload(self, user: User, req: ProfileUploadInitRequest) -> UploadInitResponse:
        self._validate_declared(req.filename, req.content_type, req.size_bytes)
        key = f"{KEY_ROOT}/profiles/{user.id}/{uuid.uuid4()}.{ext_for(req.content_type)}"
        return await self._presign(key, req.content_type, {"purpose": "profile_image", "uid": str(user.id)})

    async def confirm_profile_upload(self, user: User, token: str, ctx: RequestContext) -> AvatarOut:
        c = self._claims(token, user, "profile_image")
        key = c["key"]
        if user.profile is not None and user.profile.avatar_s3_key == key:
            return AvatarOut(url=await self.resolver.url_for(key))
        await self._fetch_validated(key, c["ct"])
        old_key: str | None = None
        try:
            async with transactional(self.session):
                if user.profile is None:
                    user.profile = UserProfile(display_name=user.full_name)
                old_key, user.profile.avatar_s3_key = user.profile.avatar_s3_key, key
                self.audit.record(action="profile.avatar_changed", entity_type="user", entity_id=user.id,
                                  actor=Actor(user.id, user.role), ip=ctx.ip)
        except AppError:
            await self.storage.delete(key)
            raise
        if old_key:
            await self.storage.delete(old_key)
        return AvatarOut(url=await self.resolver.url_for(key))
