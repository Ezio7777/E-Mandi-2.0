"""Farmer quality-certificate PDFs: init (presigned POST, application/pdf only) -> direct upload to S3 -> confirm
(server-side validation) -> admin review. Files stay private: reads are short-lived presigned URLs, and buyers only ever
see VERIFIED documents. A document is evidence for a human reviewer; it never changes prices, grades or inventory."""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import transactional
from app.core.errors import AppError, ConflictError, DomainValidationError, ForbiddenError, NotFoundError
from app.core.security import sign_token, verify_signed_token
from app.integrations.aws.s3 import ObjectStorage
from app.models.enums import DocumentStatus, DocumentType, ListingStatus, NotificationType, UserRole
from app.models.listing_document import ListingDocument
from app.models.user import User
from app.repositories.document import DocumentRepository
from app.repositories.listing import ListingRepository
from app.schemas.document import DocumentInitRequest, DocumentOut, DocumentPage
from app.schemas.image import UploadInitResponse
from app.services.access import assert_can_view_listing, assert_owner_listing
from app.services.audit import Actor, AuditService, RequestContext
from app.services.image import KEY_ROOT, UPLOAD_TOKEN_TTL
from app.services.notification import NotificationService
from app.utils.hashing import sha256_hex
from app.utils.pagination import decode_cursor, encode_cursor
from app.utils.pdf import InvalidPdf, sniff_pdf
from app.utils.time import utcnow

PDF = "application/pdf"
PURPOSE = "listing_document"
EDITABLE = {ListingStatus.DRAFT, ListingStatus.ACTIVE, ListingStatus.REVIEW_REQUIRED}


class DocumentService:
    def __init__(self, session: AsyncSession, settings: Settings, storage: ObjectStorage) -> None:
        self.session, self.settings, self.storage = session, settings, storage
        self.docs, self.listings = DocumentRepository(session), ListingRepository(session)
        self.audit, self.notify = AuditService(session), NotificationService(session)

    async def to_out(self, d: ListingDocument) -> DocumentOut:
        url = await self.storage.presign_get(d.s3_key, self.settings.S3_READ_URL_EXPIRE_SECONDS)  # always private, never CDN
        return DocumentOut(id=d.id, listing_id=d.listing_id, url=url, doc_type=d.doc_type, title=d.title, status=d.status,
                           size_bytes=d.size_bytes, page_count=d.page_count, review_reason=d.review_reason,
                           reviewed_at=d.reviewed_at, created_at=d.created_at)

    # ------------------------------------------------------------------ upload
    def _validate_declared(self, filename: str, content_type: str, size: int) -> None:
        if content_type != PDF:
            raise DomainValidationError("Only PDF documents are allowed", details=[{"field": "contentType", "message": "must be application/pdf"}])
        if not filename.lower().endswith(".pdf"):
            raise DomainValidationError("File extension does not match content type", details=[{"field": "filename", "message": "must end in .pdf"}])
        if size > self.settings.DOCUMENT_MAX_BYTES:
            raise DomainValidationError(f"File too large (max {self.settings.DOCUMENT_MAX_BYTES // (1024 * 1024)} MB)",
                                        details=[{"field": "sizeBytes", "message": "too large"}])

    async def init_upload(self, user: User, req: DocumentInitRequest) -> UploadInitResponse:
        self._validate_declared(req.filename, req.content_type, req.size_bytes)
        listing = assert_owner_listing(user, await self.listings.get(req.listing_id))
        if listing.status not in EDITABLE:
            raise ConflictError(f"Documents cannot be changed while the listing is {listing.status.value}")
        if await self.docs.count_for_listing(listing.id) >= self.settings.DOCUMENT_MAX_PER_LISTING:
            raise ConflictError(f"A listing can have at most {self.settings.DOCUMENT_MAX_PER_LISTING} documents")
        s = self.settings
        key = f"{KEY_ROOT}/listings/{listing.id}/{uuid.uuid4()}.pdf"
        post = await self.storage.presign_post(key, PDF, s.DOCUMENT_MAX_BYTES, s.S3_PRESIGN_EXPIRE_SECONDS)
        token = sign_token({"purpose": PURPOSE, "uid": str(user.id), "lid": str(listing.id), "key": key, "ct": PDF,
                            "dt": req.doc_type.value, "ti": req.title}, typ="upload", ttl_seconds=UPLOAD_TOKEN_TTL, settings=s)
        return UploadInitResponse(upload_token=token, url=post.url, fields=post.fields, object_key=key,
                                  expires_in=s.S3_PRESIGN_EXPIRE_SECONDS, max_bytes=s.DOCUMENT_MAX_BYTES)

    async def _fetch_validated(self, key: str) -> tuple[bytes, int]:
        s = self.settings
        try:
            head = await self.storage.head(key)
            if head is None:
                raise DomainValidationError("Upload not found - please upload the file first")
            if head.size <= 0 or head.size > s.DOCUMENT_MAX_BYTES:
                raise DomainValidationError("File size is not allowed")
            data = await self.storage.get_bytes(key, s.DOCUMENT_MAX_BYTES)
            try:
                info = sniff_pdf(data, max_pages=s.DOCUMENT_MAX_PAGES)
            except InvalidPdf as exc:
                raise DomainValidationError(str(exc)) from exc
            return data, info.pages
        except AppError:
            await self.storage.delete(key)  # unvalidated files never linger
            raise

    async def confirm_upload(self, user: User, token: str, ctx: RequestContext) -> tuple[ListingDocument, bool]:
        c = verify_signed_token(token, typ="upload", settings=self.settings)
        if c.get("uid") != str(user.id) or c.get("purpose") != PURPOSE:
            raise ForbiddenError("This upload grant does not belong to you")
        key, listing_id = c["key"], uuid.UUID(c["lid"])
        existing = await self.docs.get_by_key(key)
        if existing is not None:  # idempotent replay
            return existing, False
        data, pages = await self._fetch_validated(key)
        try:
            async with transactional(self.session):
                listing = await self.listings.get_for_update(listing_id)
                assert_owner_listing(user, listing)
                assert listing is not None
                if listing.status not in EDITABLE:
                    raise ConflictError(f"Documents cannot be changed while the listing is {listing.status.value}")
                if await self.docs.count_for_listing(listing.id) >= self.settings.DOCUMENT_MAX_PER_LISTING:
                    raise ConflictError("Document limit reached for this listing")
                doc = await self.docs.add(ListingDocument(
                    listing_id=listing.id, uploaded_by=user.id, s3_key=key, content_type=PDF, size_bytes=len(data), page_count=pages,
                    sha256=sha256_hex(data), doc_type=DocumentType(c["dt"]), title=c["ti"]))
                self.audit.record(action="document.uploaded", entity_type="listing_document", entity_id=doc.id,
                                  actor=Actor(user.id, user.role), ip=ctx.ip,
                                  metadata={"listing_id": str(listing.id), "size_bytes": len(data), "pages": pages, "sha256": doc.sha256})
                await self.notify.notify_admins(NotificationType.REVIEW_REQUIRED, "Document awaiting review",
                                                f"A {doc.doc_type.value.replace('_', ' ').lower()} was uploaded for listing {str(listing.id)[:8]}.",
                                                {"document_id": str(doc.id), "listing_id": str(listing.id)})
        except AppError:
            await self.storage.delete(key)
            raise
        return doc, True

    # ------------------------------------------------------------------ read / delete
    async def list_for_listing(self, user: User, listing_id: uuid.UUID) -> list[DocumentOut]:
        listing = assert_can_view_listing(user, await self.listings.get(listing_id))
        privileged = user.role == UserRole.ADMIN or listing.farmer_id == user.id
        return [await self.to_out(d) for d in await self.docs.list_for_listing(listing_id, only_verified=not privileged)]

    async def delete(self, user: User, doc_id: uuid.UUID, ctx: RequestContext) -> None:
        async with transactional(self.session):
            doc = await self.docs.get(doc_id)
            if doc is None:
                raise NotFoundError("Document not found")
            listing = await self.listings.get_for_update(doc.listing_id)
            assert_owner_listing(user, listing, allow_admin=True)
            key = doc.s3_key
            await self.docs.delete(doc)
            self.audit.record(action="document.deleted", entity_type="listing_document", entity_id=doc_id, actor=Actor(user.id, user.role),
                              ip=ctx.ip, metadata={"listing_id": str(doc.listing_id)}, previous_state={"s3_key": key, "status": doc.status.value})
        await self.storage.delete(key)

    # ------------------------------------------------------------------ admin review
    async def pending(self, status: DocumentStatus, cursor: str | None, limit: int) -> DocumentPage:
        rows = await self.docs.list_by_status(status, decode_cursor(cursor) if cursor else None, limit)
        more, rows = len(rows) > limit, rows[:limit]
        return DocumentPage(items=[await self.to_out(r) for r in rows],
                            next_cursor=encode_cursor(rows[-1].created_at, rows[-1].id) if more else None)

    async def review(self, admin: User, doc_id: uuid.UUID, approve: bool, reason: str | None, ctx: RequestContext) -> ListingDocument:
        async with transactional(self.session):
            doc = await self.docs.get(doc_id, for_update=True)
            if doc is None:
                raise NotFoundError("Document not found")
            if doc.status != DocumentStatus.PENDING_REVIEW:
                raise ConflictError(f"Document is already {doc.status.value}")
            prev = doc.status
            doc.status = DocumentStatus.VERIFIED if approve else DocumentStatus.REJECTED
            doc.reviewed_by, doc.reviewed_at, doc.review_reason = admin.id, utcnow(), reason
            self.audit.record(action="document.verified" if approve else "document.rejected", entity_type="listing_document", entity_id=doc.id,
                              actor=Actor(admin.id, admin.role), ip=ctx.ip, metadata={"reason": reason, "listing_id": str(doc.listing_id)},
                              previous_state={"status": prev.value}, new_state={"status": doc.status.value})
            self.notify.add(doc.uploaded_by, NotificationType.SYSTEM, "Document verified" if approve else "Document rejected",
                            f"Your document \"{doc.title}\" was {'verified' if approve else 'rejected: ' + (reason or '')}.",
                            {"document_id": str(doc.id), "listing_id": str(doc.listing_id)})
        return doc
