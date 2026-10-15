import asyncio
from typing import Any

from google import genai
from google.genai import types

from app.core.config import Settings
from app.core.logging import get_logger
from app.integrations.llm_common import LLMProviderError

log = get_logger(__name__)


class GeminiTextLLM:
    name = "gemini"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.model, self.timeout = settings.GEMINI_TEXT_MODEL, settings.AI_PROVIDER_TIMEOUT_SECONDS
        key = settings.GEMINI_API_KEY.get_secret_value()
        self.client: Any = client or (genai.Client(api_key=key) if (key and self.model) else None)

    @property
    def available(self) -> bool:
        return self.client is not None

    async def complete_json(self, system: str, user: str) -> str:
        if not self.available:
            raise LLMProviderError("not_configured", self.name)
        try:
            resp = await asyncio.wait_for(self.client.aio.models.generate_content(
                model=self.model, contents=user,
                config=types.GenerateContentConfig(system_instruction=system, temperature=0.2,
                                                   response_mime_type="application/json")), self.timeout)
        except TimeoutError as exc:
            raise LLMProviderError("timeout", self.name) from exc
        except Exception as exc:
            log.warning("gemini_text_failed", error_type=type(exc).__name__)
            raise LLMProviderError("api_error", self.name) from exc
        return getattr(resp, "text", None) or ""
