import logging

import pytest
from app.core.config import Settings
from app.core.errors import AppError
from app.integrations.sms import (
    ConsoleOTPSender,
    OtpDeliveryFailed,
    OtpUnavailable,
    SnsOTPSender,
    UnconfiguredOTPSender,
    build_otp_sender,
    mask_phone,
)
from botocore.exceptions import ClientError

PROD = {"ENVIRONMENT": "production", "JWT_SECRET": "j" * 40, "DATABASE_URL": "postgresql+asyncpg://u:realpw@db/x"}


class FakeSns:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls, self.error = [], error

    def publish(self, **kw):
        if self.error:
            raise self.error
        self.calls.append(kw)
        return {"MessageId": "m1"}


def sns(client, **over):
    return SnsOTPSender(Settings(ENVIRONMENT="test", **over), client)


async def test_sns_sends_transactional_message_with_sender_id():
    c = FakeSns()
    await sns(c, SMS_SENDER_ID="EMANDI").send("+919876543210", "123456")
    call = c.calls[0]
    assert call["PhoneNumber"] == "+919876543210" and "123456" in call["Message"] and "5 minutes" in call["Message"]
    attrs = call["MessageAttributes"]
    assert attrs["AWS.SNS.SMS.SMSType"]["StringValue"] == "Transactional" and attrs["AWS.SNS.SMS.SenderID"]["StringValue"] == "EMANDI"


async def test_sns_without_sender_id_omits_the_attribute():
    c = FakeSns()
    await sns(c).send("+919876543210", "123456")
    assert "AWS.SNS.SMS.SenderID" not in c.calls[0]["MessageAttributes"]


@pytest.mark.parametrize("phone", ["9876543210", "+0123456789", "+91 98765 43210", "+91abc", "", "+1"])
async def test_non_e164_numbers_are_never_sent(phone):
    c = FakeSns()
    with pytest.raises(OtpDeliveryFailed):
        await sns(c).send(phone, "123456")
    assert c.calls == []


async def test_provider_errors_are_generic_and_never_log_the_code(caplog):
    err = ClientError({"Error": {"Code": "Throttling", "Message": "secret internal detail"}}, "Publish")
    with caplog.at_level(logging.DEBUG), pytest.raises(OtpDeliveryFailed) as ei:
        await sns(FakeSns(err)).send("+919876543210", "654321")
    assert "secret internal detail" not in str(ei.value) and ei.value.status_code == 503
    assert "654321" not in caplog.text and "+919876543210" not in caplog.text


def test_mask_phone():
    assert mask_phone("+919876543210") == "+91********10" and mask_phone("123") == "***"


def test_template_is_configurable_for_dlt():
    s = sns(FakeSns(), SMS_TEMPLATE="{code} is your E-MANDI OTP valid for {minutes} min.")
    assert s.render("111222") == "111222 is your E-MANDI OTP valid for 5 min."


def test_factory_selection():
    assert isinstance(build_otp_sender(Settings(ENVIRONMENT="development")), ConsoleOTPSender)
    assert isinstance(build_otp_sender(Settings(**PROD)), UnconfiguredOTPSender)
    assert isinstance(build_otp_sender(Settings(ENVIRONMENT="test", SMS_PROVIDER="sns", AWS_REGION="ap-south-1")), SnsOTPSender)


def test_console_sender_is_refused_in_production():
    with pytest.raises(ValueError, match="console"):
        Settings(**PROD, SMS_PROVIDER="console")


async def test_unconfigured_sender_raises_503():
    with pytest.raises(OtpUnavailable) as ei:
        await UnconfiguredOTPSender().send("+919876543210", "1")
    assert isinstance(ei.value, AppError) and ei.value.status_code == 503
