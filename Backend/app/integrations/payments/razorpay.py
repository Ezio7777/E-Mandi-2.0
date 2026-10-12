"""Razorpay adapter (Orders + Refunds REST API, webhook HMAC-SHA256). Use Razorpay TEST MODE keys for the portfolio.
Written against Razorpay's documented formats; verify end-to-end in Test Mode before relying on it."""
import httpx

from app.core.config import Settings
from app.core.errors import ProviderError
from app.core.logging import get_logger
from app.integrations.payments.base import ProviderOrder, ProviderRefund, WebhookEvent, parse_razorpay_shape, verify_hmac

log = get_logger(__name__)
BASE_URL = "https://api.razorpay.com/v1"


class RazorpayProvider:
    name = "razorpay"
    signature_header = "X-Razorpay-Signature"
    event_id_header = "X-Razorpay-Event-Id"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._key_id = settings.PAYMENT_KEY_ID
        self._secret = settings.PAYMENT_KEY_SECRET.get_secret_value()
        self._webhook_secret = settings.PAYMENT_WEBHOOK_SECRET.get_secret_value()
        self._timeout = settings.AI_PROVIDER_TIMEOUT_SECONDS
        self._client = client

    @property
    def public_key_id(self) -> str:
        return self._key_id

    async def _post(self, path: str, payload: dict) -> dict:
        if not (self._key_id and self._secret):
            raise ProviderError("Payment provider is not configured")
        try:
            async with (self._client or httpx.AsyncClient(timeout=self._timeout)) as c:
                r = await c.post(f"{BASE_URL}{path}", json=payload, auth=(self._key_id, self._secret))
            if r.status_code >= 400:
                log.error("razorpay_error", path=path, status=r.status_code)  # never log the body (may echo payment data)
                raise ProviderError("Payment provider rejected the request")
            return r.json()
        except httpx.HTTPError as exc:
            log.error("razorpay_unreachable", path=path, error_type=type(exc).__name__)
            raise ProviderError("Payment provider is unavailable") from exc

    async def create_order(self, *, amount_paise: int, currency: str, receipt: str, notes: dict[str, str]) -> ProviderOrder:
        d = await self._post("/orders", {"amount": amount_paise, "currency": currency, "receipt": receipt[:40], "notes": notes})
        if int(d.get("amount", -1)) != amount_paise or not d.get("id"):  # never trust a provider echo blindly
            raise ProviderError("Unexpected response from payment provider")
        return ProviderOrder(d["id"], amount_paise, d.get("currency", currency), d.get("status", "created"))

    async def create_refund(self, *, provider_payment_id: str, amount_paise: int, notes: dict[str, str]) -> ProviderRefund:
        d = await self._post(f"/payments/{provider_payment_id}/refund", {"amount": amount_paise, "notes": notes})
        if not d.get("id"):
            raise ProviderError("Unexpected response from payment provider")
        return ProviderRefund(d["id"], "processed" if d.get("status") == "processed" else "pending")

    def verify_webhook(self, raw_body: bytes, signature: str | None) -> bool:
        return verify_hmac(self._webhook_secret, raw_body, signature)

    def parse_webhook(self, raw_body: bytes, header_event_id: str | None) -> WebhookEvent | None:
        return parse_razorpay_shape(raw_body, header_event_id)
