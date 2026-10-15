import asyncio
from typing import Any

from google import genai
from google.genai import types

from app.core.config import Settings
from app.core.logging import get_logger
from app.integrations.vision_common import (
    SYSTEM_PROMPT,
    GradingProviderError,
    parse_raw_grading,
    user_prompt,
)
from app.schemas.grading import RawGrading

log = get_logger(__name__)


class GeminiVisionGrader:
    name = "gemini"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.model = settings.GEMINI_VISION_MODEL
        self.timeout = settings.AI_PROVIDER_TIMEOUT_SECONDS
        key = settings.GEMINI_API_KEY.get_secret_value()
        self._configured = bool(key and self.model)
        self.client: Any = client or (genai.Client(api_key=key) if self._configured else None)

    @property
    def available(self) -> bool:
        return self._configured or self.client is not None

    async def grade(self, image: bytes, content_type: str, crop_name: str) -> RawGrading:
        if not self.available:
            raise GradingProviderError("not_configured", self.name)
        try:
            resp = await asyncio.wait_for(self.client.aio.models.generate_content(
                model=self.model,
                contents=[types.Part.from_bytes(data=image, mime_type=content_type), user_prompt(crop_name)],
                config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, temperature=0,
                                                   response_mime_type="application/json")),
                timeout=self.timeout)
        except TimeoutError as exc:
            raise GradingProviderError("timeout", self.name) from exc
        except Exception as exc:
            log.warning("gemini_call_failed", error_type=type(exc).__name__)
            raise GradingProviderError("api_error", self.name) from exc
        return parse_raw_grading(getattr(resp, "text", None) or "", self.name)
