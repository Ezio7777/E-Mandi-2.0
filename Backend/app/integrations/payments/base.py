"""Payment provider abstraction + shared webhook primitives. Business logic only ever sees these types."""
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderOrder:
    provider_order_id: str
    amount_paise: int
    currency: str
    status: str


@dataclass(frozen=True)
class ProviderRefund:
    provider_refund_id: str
    status: str  # "processed" (done) | "pending" (completion arrives by webhook)


@dataclass(frozen=True)
class WebhookEvent:
    """Provider-neutral event. type in: payment.captured | payment.failed | refund.processed | refund.failed"""
    event_id: str
    type: str
    provider_order_id: str | None = None
    provider_payment_id: str | None = None
    provider_refund_id: str | None = None
    amount_paise: int | None = None
    currency: str | None = None
    method: str | None = None
    failure_code: str | None = None
    failure_reason: str | None = None

    def normalized(self) -> dict[str, Any]:
        """The ONLY thing persisted from a webhook: no emails, phone numbers or card details."""
        return {k: v for k, v in self.__dict__.items() if v is not None}


class PaymentProvider(Protocol):
    name: str
    signature_header: str
    event_id_header: str

    @property
    def public_key_id(self) -> str: ...
    async def create_order(self, *, amount_paise: int, currency: str, receipt: str, notes: dict[str, str]) -> ProviderOrder: ...
    async def create_refund(self, *, provider_payment_id: str, amount_paise: int, notes: dict[str, str]) -> ProviderRefund: ...
    def verify_webhook(self, raw_body: bytes, signature: str | None) -> bool: ...
    def parse_webhook(self, raw_body: bytes, header_event_id: str | None) -> WebhookEvent | None: ...


def hmac_hex(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_hmac(secret: str, body: bytes, signature: str | None) -> bool:
    """Constant-time check. An unset secret FAILS CLOSED (never accept unsigned/any-signed webhooks)."""
    if not secret or not signature:
        return False
    return hmac.compare_digest(hmac_hex(secret, body), signature.strip().lower())


def parse_razorpay_shape(raw_body: bytes, header_event_id: str | None) -> WebhookEvent | None:
    """Parses Razorpay's documented webhook JSON (also used by the mock provider so both take the same code path).
    Returns None for event types we do not act on. Raises ValueError for malformed payloads."""
    try:
        doc = json.loads(raw_body)
        etype, payload = doc["event"], doc.get("payload", {})
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("malformed webhook body") from exc
    event_id = header_event_id or "sha256:" + hashlib.sha256(raw_body).hexdigest()
    pay = (payload.get("payment") or {}).get("entity") or {}
    if etype in ("payment.captured", "payment.failed"):
        if not pay.get("order_id") or not pay.get("id"):
            raise ValueError("payment event without order/payment id")
        return WebhookEvent(
            event_id, etype, provider_order_id=pay["order_id"], provider_payment_id=pay["id"],
            amount_paise=int(pay["amount"]) if pay.get("amount") is not None else None, currency=pay.get("currency"),
            method=pay.get("method"), failure_code=pay.get("error_code"),
            failure_reason=(pay.get("error_description") or pay.get("error_reason")))
    if etype in ("refund.processed", "refund.failed"):
        ref = (payload.get("refund") or {}).get("entity") or {}
        if not ref.get("id"):
            raise ValueError("refund event without refund id")
        return WebhookEvent(event_id, etype, provider_order_id=pay.get("order_id"), provider_payment_id=ref.get("payment_id") or pay.get("id"),
                            provider_refund_id=ref["id"], amount_paise=int(ref["amount"]) if ref.get("amount") is not None else None,
                            currency=ref.get("currency"))
    return None
