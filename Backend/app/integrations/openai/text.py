import asyncio
from typing import Any

from openai import AsyncOpenAI

from app.core.config import Settings
from app.core.logging import get_logger
from app.integrations.llm_common import LLMProviderError

log = get_logger(__name__)


class OpenAITextLLM:
    name = "openai"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.model, self.timeout = settings.OPENAI_TEXT_MODEL, settings.AI_PROVIDER_TIMEOUT_SECONDS
        key = settings.OPENAI_API_KEY.get_secret_value()
        self.client = client or (AsyncOpenAI(api_key=key, timeout=self.timeout) if (key and self.model) else None)

    @property
    def available(self) -> bool:
        return self.client is not None

    async def complete_json(self, system: str, user: str) -> str:
        if not self.available:
            raise LLMProviderError("not_configured", self.name)
        try:
            resp = await asyncio.wait_for(self.client.chat.completions.create(
                model=self.model, response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}]), self.timeout)
            return resp.choices[0].message.content or ""
        except (TimeoutError, asyncio.TimeoutError) as exc:
            raise LLMProviderError("timeout", self.name) from exc
        except Exception as exc:  # noqa: BLE001
            log.warning("openai_text_failed", error_type=type(exc).__name__)
            raise LLMProviderError("api_error", self.name) from exc
