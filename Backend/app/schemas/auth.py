import re
import uuid
from typing import Literal

from pydantic import EmailStr, Field, field_validator

from app.schemas.common import CamelModel
from app.schemas.user import UserOut

# Self-service signup may only ever create these roles. ADMIN is never user-selectable.
SelfServiceRole = Literal["FARMER", "BUYER"]
_PHONE_RE = re.compile(r"^\+[1-9]\d{9,14}$")


def normalize_phone(raw: str) -> str:
    p = re.sub(r"[\s\-()]", "", raw)
    if re.fullmatch(r"[6-9]\d{9}", p):  # bare Indian mobile number
        p = "+91" + p
    elif re.fullmatch(r"91[6-9]\d{9}", p):
        p = "+" + p
    if not _PHONE_RE.fullmatch(p):
        raise ValueError("Invalid phone number")
    return p


class RegisterRequest(CamelModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    role: SelfServiceRole
    phone: str | None = None

    @field_validator("password")
    @classmethod
    def _strong(cls, v: str) -> str:
        if not (re.search(r"[A-Za-z]", v) and re.search(r"\d", v)):
            raise ValueError("Password must contain letters and digits")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return normalize_phone(v) if v else v


class LoginRequest(CamelModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class OtpRequest(CamelModel):
    phone: str

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalize_phone(v)


class OtpChallengeOut(CamelModel):
    challenge_id: uuid.UUID
    expires_in: int


class OtpVerifyRequest(CamelModel):
    challenge_id: uuid.UUID
    code: str = Field(min_length=4, max_length=10, pattern=r"^\d+$")
    role: SelfServiceRole = "BUYER"  # only used if this phone number creates a NEW account
    full_name: str | None = Field(None, max_length=200)


class GoogleLoginRequest(CamelModel):
    credential: str = Field(min_length=20, max_length=4096)
    role: SelfServiceRole = "BUYER"  # only used when a NEW account is created


class RefreshRequest(CamelModel):
    refresh_token: str = Field(min_length=20, max_length=256)


class TokenResponse(CamelModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105  (OAuth token type, not a secret)
    expires_in: int
    is_demo: bool = False
    user: UserOut


class DemoAccountOut(CamelModel):
    kind: Literal["farmer", "buyer", "admin"]
    label: str
