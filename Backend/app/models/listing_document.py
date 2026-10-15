import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, pg_enum, uuid_pk
from app.models.enums import DocumentStatus, DocumentType


class ListingDocument(Base):
    """A farmer-supplied PDF (quality/organic certificate, lab report). Metadata only; the binary lives in S3 under a
    server-generated key. A document is never treated as trusted until an admin marks it VERIFIED."""
    __tablename__ = "listing_documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), index=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    s3_key: Mapped[str] = mapped_column(String(500), unique=True)
    content_type: Mapped[str] = mapped_column(String(100), default="application/pdf")
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    page_count: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    doc_type: Mapped[DocumentType] = mapped_column(pg_enum(DocumentType))
    title: Mapped[str] = mapped_column(String(120))
    status: Mapped[DocumentStatus] = mapped_column(pg_enum(DocumentStatus), default=DocumentStatus.PENDING_REVIEW, index=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
