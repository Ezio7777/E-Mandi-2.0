import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import UserRole


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    display_name: str | None = None
    business_name: str | None = None
    bio: str | None = None
    city: str | None = None
    state: str | None = None
    pincode: str | None = None
    preferred_language: str = "en"


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(None, max_length=200)
    business_name: str | None = Field(None, max_length=200)
    bio: str | None = Field(None, max_length=2000)
    city: str | None = Field(None, max_length=120)
    state: str | None = Field(None, max_length=120)
    pincode: str | None = Field(None, pattern=r"^\d{6}$")
    preferred_language: Literal["en", "hi", "kn"] | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str | None
    phone: str | None
    full_name: str
    role: UserRole
    is_demo: bool
    email_verified: bool
    phone_verified: bool
    created_at: datetime
    profile: ProfileOut | None = None
