"""OTP delivery abstraction. Real SMS providers plug in behind OTPSender."""
import asyncio
import re
from typing import Any, Protocol

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger

log = get_logger(__name__)
E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")


class OtpUnavailable(AppError):
    status_code, code, message = 503, "otp_unavailable", "OTP delivery is not configured"


class OtpDeliveryFailed(AppError):
    status_code, code, message = 503, "otp_delivery_failed", "We could not send the verification code. Please try again shortly."


class OTPSender(Protocol):
    async def send(self, phone: str, code: str) -> None: ...


def mask_phone(phone: str) -> str:
    return f"{phone[:3]}{'*' * max(0, len(phone) - 5)}{phone[-2:]}" if len(phone) > 5 else "***"


class ConsoleOTPSender:
    """Dev/demo only: writes the code to the server log. Refused in production."""

    async def send(self, phone: str, code: str) -> None:
        log.warning(f"DEV OTP for {phone}: {code}")


class UnconfiguredOTPSender:
    async def send(self, phone: str, code: str) -> None:
        raise OtpUnavailable()


class SnsOTPSender:
    """AWS SNS transactional SMS (uses the EC2 instance role; no extra vendor key). The code is never logged; phones are masked.
    India note: operators require DLT registration of the sender ID and message template - set SMS_SENDER_ID and make SMS_TEMPLATE
    match the registered template exactly."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.template, self.sender_id = settings.SMS_TEMPLATE, settings.SMS_SENDER_ID
        self.ttl_minutes = max(1, settings.OTP_TTL_SECONDS // 60)
        self.client: Any = client or boto3.client("sns", region_name=settings.SMS_AWS_REGION or settings.AWS_REGION)

    def render(self, code: str) -> str:
        return self.template.format(code=code, minutes=self.ttl_minutes)

    async def send(self, phone: str, code: str) -> None:
        if not E164.match(phone):
            raise OtpDeliveryFailed()
        attrs: dict[str, Any] = {"AWS.SNS.SMS.SMSType": {"DataType": "String", "StringValue": "Transactional"}}
        if self.sender_id:
            attrs["AWS.SNS.SMS.SenderID"] = {"DataType": "String", "StringValue": self.sender_id}
        try:
            await asyncio.to_thread(self.client.publish, PhoneNumber=phone, Message=self.render(code), MessageAttributes=attrs)
        except (ClientError, BotoCoreError) as exc:
            err = exc.response.get("Error", {}).get("Code", "") if isinstance(exc, ClientError) else type(exc).__name__
            log.error("sms_send_failed", phone=mask_phone(phone), error=err)
            raise OtpDeliveryFailed() from exc
        log.info("sms_sent", phone=mask_phone(phone))


def build_otp_sender(settings: Settings) -> OTPSender:
    provider = settings.SMS_PROVIDER
    if provider == "sns":
        return SnsOTPSender(settings)
    if provider == "console":
        return ConsoleOTPSender()
    return UnconfiguredOTPSender() if settings.is_production else ConsoleOTPSender()  # "auto"
