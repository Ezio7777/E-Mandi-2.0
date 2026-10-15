import uuid
from datetime import datetime

from pydantic import Field

from app.models.enums import DocumentStatus, DocumentType
from app.schemas.common import CamelModel


class DocumentInitRequest(CamelModel):
    listing_id: uuid.UUID
    filename: str = Field(min_length=1, max_length=255)  # informational; never used to build keys
    content_type: str = Field(max_length=100)
    size_bytes: int = Field(gt=0)
    doc_type: DocumentType = DocumentType.QUALITY_CERTIFICATE
    title: str = Field(default="Quality certificate", min_length=1, max_length=120)


class DocumentConfirmRequest(CamelModel):
    upload_token: str = Field(min_length=20, max_length=4096)


class DocumentRejectRequest(CamelModel):
    reason: str = Field(min_length=3, max_length=500)


class DocumentOut(CamelModel):
    id: uuid.UUID
    listing_id: uuid.UUID
    url: str  # short-lived presigned GET
    doc_type: DocumentType
    title: str
    status: DocumentStatus
    size_bytes: int
    page_count: int
    review_reason: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime


class DocumentPage(CamelModel):
    items: list[DocumentOut]
    next_cursor: str | None = None
