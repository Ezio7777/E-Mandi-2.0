import json

import httpx
import pytest
import respx

from app.core.config import Settings
from app.core.errors import ProviderError
from app.integrations.payments.base import hmac_hex, parse_razorpay_shape, verify_hmac
from app.integrations.payments.mock import MockPaymentProvider
from app.integrations.payments.razorpay import BASE_URL, RazorpayProvider

SECRET = "whsec-unit-test-0123456789"
S = Settings(ENVIRONMENT="test", JWT_SECRET="x" * 40, PAYMENT_KEY_ID="rzp_test_abc", PAYMENT_KEY_SECRET="keysecret",
             PAYMENT_WEBHOOK_SECRET=SECRET, AI_PROVIDER_TIMEOUT_SECONDS=2)
BODY = MockPaymentProvider.payment_event("captured", provider_order_id="order_1", amount_paise=5000, payment_id="pay_1")


def test_hmac_verification():
    sig = hmac_hex(SECRET, BODY)
    assert verify_hmac(SECRET, BODY, sig) and verify_hmac(SECRET, BODY, sig.upper()) and verify_hmac(SECRET, BODY, f" {sig} ")
    assert not verify_hmac(SECRET, BODY + b" ", sig)  # tampered body
    assert not verify_hmac("other-secret", BODY, sig) and not verify_hmac(SECRET, BODY, "0" * 64)
    assert not verify_hmac(SECRET, BODY, None) and not verify_hmac(SECRET, BODY, "")


def test_unset_secret_fails_closed():
    assert not verify_hmac("", BODY, hmac_hex("", BODY))  # even a "valid" signature from an empty key is rejected
    nosecret = Settings(ENVIRONMENT="test", JWT_SECRET="x" * 40, PAYMENT_WEBHOOK_SECRET="")  # env value explicitly cleared
    assert not MockPaymentProvider(nosecret).verify_webhook(BODY, hmac_hex("", BODY))
    assert not RazorpayProvider(nosecret).verify_webhook(BODY, hmac_hex("", BODY))
    assert not RazorpayProvider(nosecret).verify_webhook(BODY, None)


def test_parse_events():
    e = parse_razorpay_shape(BODY, "evt_1")
    assert (e.event_id, e.type, e.provider_order_id, e.provider_payment_id, e.amount_paise, e.currency, e.method) == (
        "evt_1", "payment.captured", "order_1", "pay_1", 5000, "INR", "upi")
    f = parse_razorpay_shape(MockPaymentProvider.payment_event("failed", provider_order_id="o", amount_paise=1, reason="Insufficient funds"), "e")
    assert f.type == "payment.failed" and f.failure_reason == "Insufficient funds" and f.failure_code
    r = parse_razorpay_shape(MockPaymentProvider.refund_event("processed", refund_id="rfnd_1", payment_id="pay_1", amount_paise=300), "e")
    assert (r.type, r.provider_refund_id, r.provider_payment_id, r.amount_paise) == ("refund.processed", "rfnd_1", "pay_1", 300)
    assert parse_razorpay_shape(json.dumps({"event": "order.paid", "payload": {}}).encode(), "e") is None  # not acted on


def test_event_id_falls_back_to_body_hash_and_normalized_has_no_pii():
    raw = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {
        "id": "pay_1", "order_id": "o1", "amount": 100, "currency": "INR", "email": "a@b.com", "contact": "+911234567890",
        "card": {"last4": "1111"}}}}}).encode()
    e = parse_razorpay_shape(raw, None)
    assert e.event_id.startswith("sha256:") and parse_razorpay_shape(raw, None).event_id == e.event_id
    flat = json.dumps(e.normalized())
    assert "a@b.com" not in flat and "1234567890" not in flat and "1111" not in flat and None not in e.normalized().values()


@pytest.mark.parametrize("raw", [b"not json", b"{}", b'{"event": "payment.captured", "payload": {}}',
                                 b'{"event": "payment.captured", "payload": {"payment": {"entity": {"id": "p"}}}}',
                                 b'{"event": "refund.processed", "payload": {"refund": {"entity": {}}}}', b"[]"])
def test_malformed_events_rejected(raw):
    with pytest.raises(ValueError):
        parse_razorpay_shape(raw, "e")


@respx.mock
async def test_razorpay_create_order_request_and_response():
    route = respx.post(f"{BASE_URL}/orders").mock(return_value=httpx.Response(200, json={
        "id": "order_Rz1", "amount": 150000, "currency": "INR", "status": "created"}))
    o = await RazorpayProvider(S).create_order(amount_paise=150000, currency="INR", receipt="r" * 60, notes={"order_id": "1"})
    assert (o.provider_order_id, o.amount_paise, o.status) == ("order_Rz1", 150000, "created")
    req = route.calls[0].request
    sent = json.loads(req.content)
    assert sent["amount"] == 150000 and sent["currency"] == "INR" and len(sent["receipt"]) == 40 and req.headers["authorization"].startswith("Basic ")


@respx.mock
@pytest.mark.parametrize("resp", [httpx.Response(400, json={"error": "bad"}), httpx.Response(500),
                                  httpx.Response(200, json={"id": "o", "amount": 1, "currency": "INR"}),  # amount echo mismatch
                                  httpx.Response(200, json={"amount": 150000})])  # no id
async def test_razorpay_rejects_bad_responses(resp):
    respx.post(f"{BASE_URL}/orders").mock(return_value=resp)
    with pytest.raises(ProviderError):
        await RazorpayProvider(S).create_order(amount_paise=150000, currency="INR", receipt="r", notes={})


@respx.mock
async def test_razorpay_network_errors_and_unconfigured():
    respx.post(f"{BASE_URL}/orders").mock(side_effect=httpx.ConnectTimeout("boom"))
    with pytest.raises(ProviderError):
        await RazorpayProvider(S).create_order(amount_paise=1, currency="INR", receipt="r", notes={})
    with pytest.raises(ProviderError):
        await RazorpayProvider(Settings(ENVIRONMENT="test", JWT_SECRET="x" * 40, PAYMENT_KEY_ID="", PAYMENT_KEY_SECRET="")).create_order(
            amount_paise=1, currency="INR", receipt="r", notes={})


@respx.mock
async def test_razorpay_refund_status_mapping():
    respx.post(f"{BASE_URL}/payments/pay_1/refund").mock(return_value=httpx.Response(200, json={"id": "rfnd_1", "status": "processed"}))
    assert (await RazorpayProvider(S).create_refund(provider_payment_id="pay_1", amount_paise=100, notes={})).status == "processed"
    respx.post(f"{BASE_URL}/payments/pay_2/refund").mock(return_value=httpx.Response(200, json={"id": "rfnd_2", "status": "pending"}))
    assert (await RazorpayProvider(S).create_refund(provider_payment_id="pay_2", amount_paise=100, notes={})).status == "pending"


def test_razorpay_webhook_roundtrip_and_headers():
    p = RazorpayProvider(S)
    assert p.verify_webhook(BODY, hmac_hex(SECRET, BODY)) and not p.verify_webhook(BODY, "bad")
    assert p.signature_header == "X-Razorpay-Signature" and p.event_id_header == "X-Razorpay-Event-Id" and p.public_key_id == "rzp_test_abc"
    assert "keysecret" not in repr(p.public_key_id)
