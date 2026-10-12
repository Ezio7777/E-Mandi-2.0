import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class UploadInitRequest(BaseModel):
    listing_id: uuid.UUID
    filename: str = Field(min_length=1, max_length=255)  # informational only; never used to build keys
    content_type: str = Field(max_length=100)
    size_bytes: int = Field(gt=0)
    replace_image_id: uuid.UUID | None = None


class ProfileUploadInitRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(max_length=100)
    size_bytes: int = Field(gt=0)


class UploadInitResponse(BaseModel):
    upload_token: str  # signed grant; must be echoed to /confirm
    url: str  # S3 presigned POST target
    fields: dict[str, str]  # send ALL of these as multipart form fields BEFORE the "file" field
    object_key: str  # S3 key the file will live under (server-generated)
    expires_in: int
    max_bytes: int


class UploadConfirmRequest(BaseModel):
    upload_token: str = Field(min_length=20, max_length=4096)


class ImageOut(BaseModel):
    id: uuid.UUID
    listing_id: uuid.UUID
    url: str
    content_type: str
    size_bytes: int
    width: int
    height: int
    is_primary: bool
    created_at: datetime


class AvatarOut(BaseModel):
    url: str


from app.schemas.pricing import CamelModel  # noqa: E402


class UploadInitIn(CamelModel):
    listing_id: uuid.UUID
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(max_length=100)
    size_bytes: int = Field(gt=0)
    replace_image_id: uuid.UUID | None = None


class UploadInitOut(CamelModel):
    """Frontend contract: { uploadUrl, fields?, objectKey } (+ the grant token to echo to /uploads/confirm)."""
    upload_url: str
    fields: dict[str, str]
    object_key: str
    upload_token: str
    expires_in: int
    max_bytes: int


class UploadConfirmIn(CamelModel):
    upload_token: str = Field(min_length=20, max_length=4096)


class UploadedImageOut(CamelModel):
    id: uuid.UUID
    listing_id: uuid.UUID
    url: str
    content_type: str
    size_bytes: int
    width: int
    height: int
    is_primary: bool
    created_at: datetime
