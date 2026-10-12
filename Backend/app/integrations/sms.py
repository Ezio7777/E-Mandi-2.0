"""OTP delivery abstraction. Real SMS providers plug in behind OTPSender."""
from typing import Protocol

from app.core.logging import get_logger

log = get_logger(__name__)


class OTPSender(Protocol):
    async def send(self, phone: str, code: str) -> None: ...


class ConsoleOTPSender:
    """Dev/demo only: writes the code to the server log. Refused in production."""

    async def send(self, phone: str, code: str) -> None:
        log.warning(f"DEV OTP for {phone}: {code}")


class UnconfiguredOTPSender:
    async def send(self, phone: str, code: str) -> None:  # noqa: ARG002
        from app.core.errors import AppError

        class OtpUnavailable(AppError):
            status_code, code, message = 503, "otp_unavailable", "OTP delivery is not configured"

        raise OtpUnavailable()
