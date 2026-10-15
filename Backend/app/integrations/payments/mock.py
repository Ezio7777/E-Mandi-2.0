"""Deterministic in-process provider for tests, demos and local development. Uses the SAME webhook format and
HMAC verification as the real adapter, so demo payments exercise the production webhook pipeline."""
import json
import uuid

from app.core.config import Settings
from app.integrations.payments.base import (
    ProviderOrder,
    ProviderRefund,
    WebhookEvent,
    hmac_hex,
    parse_razorpay_shape,
    verify_hmac,
)


class MockPaymentProvider:
    name = "mock"
    signature_header = "X-Mock-Signature"
    event_id_header = "X-Mock-Event-Id"

    def __init__(self, settings: Settings, *, refund_status: str = "processed", fail_create: bool = False) -> None:
        self._secret = settings.PAYMENT_WEBHOOK_SECRET.get_secret_value()
        self._key_id = settings.PAYMENT_KEY_ID or "mock_key_id"
        self.refund_status, self.fail_create = refund_status, fail_create
        self.orders: list[dict] = []
        self.refunds: list[dict] = []

    @property
    def public_key_id(self) -> str:
        return self._key_id

    async def create_order(self, *, amount_paise: int, currency: str, receipt: str, notes: dict[str, str]) -> ProviderOrder:
        if self.fail_create:
            from app.core.errors import ProviderError
            raise ProviderError("Payment provider is unavailable")
        oid = f"order_mock_{uuid.uuid4().hex[:14]}"
        self.orders.append({"id": oid, "amount": amount_paise, "currency": currency, "receipt": receipt})
        return ProviderOrder(oid, amount_paise, currency, "created")

    async def create_refund(self, *, provider_payment_id: str, amount_paise: int, notes: dict[str, str]) -> ProviderRefund:
        rid = f"rfnd_mock_{uuid.uuid4().hex[:14]}"
        self.refunds.append({"id": rid, "payment_id": provider_payment_id, "amount": amount_paise})
        return ProviderRefund(rid, self.refund_status)

    def verify_webhook(self, raw_body: bytes, signature: str | None) -> bool:
        return verify_hmac(self._secret, raw_body, signature)

    def parse_webhook(self, raw_body: bytes, header_event_id: str | None) -> WebhookEvent | None:
        return parse_razorpay_shape(raw_body, header_event_id)

    # ---- demo helpers: build a correctly signed webhook (used by the demo "simulate payment" endpoint and tests)
    def sign(self, raw_body: bytes) -> str:
        return hmac_hex(self._secret, raw_body)

    @staticmethod
    def payment_event(kind: str, *, provider_order_id: str, amount_paise: int, currency: str = "INR",
                      payment_id: str | None = None, reason: str | None = None) -> bytes:
        pid = payment_id or f"pay_mock_{uuid.uuid4().hex[:14]}"
        ent = {"id": pid, "order_id": provider_order_id, "amount": amount_paise, "currency": currency, "method": "upi",
               "status": "captured" if kind == "captured" else "failed"}
        if kind == "failed":
            ent.update(error_code="BAD_REQUEST_ERROR", error_description=reason or "Payment failed")
        return json.dumps({"event": f"payment.{kind}", "payload": {"payment": {"entity": ent}}}).encode()

    @staticmethod
    def refund_event(kind: str, *, refund_id: str, payment_id: str, amount_paise: int) -> bytes:
        return json.dumps({"event": f"refund.{kind}", "payload": {"refund": {"entity": {
            "id": refund_id, "payment_id": payment_id, "amount": amount_paise, "currency": "INR"}}}}).encode()
