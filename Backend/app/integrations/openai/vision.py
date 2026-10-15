import asyncio
import base64
from typing import Any

from openai import AsyncOpenAI

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


class OpenAIVisionGrader:
    name = "openai"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.model = settings.OPENAI_VISION_MODEL
        self.timeout = settings.AI_PROVIDER_TIMEOUT_SECONDS
        key = settings.OPENAI_API_KEY.get_secret_value()
        self._configured = bool(key and self.model)
        self.client: Any = client or (AsyncOpenAI(api_key=key, timeout=self.timeout) if self._configured else None)

    @property
    def available(self) -> bool:
        return self._configured or self.client is not None

    async def grade(self, image: bytes, content_type: str, crop_name: str) -> RawGrading:
        if not self.available:
            raise GradingProviderError("not_configured", self.name)
        data_url = f"data:{content_type};base64,{base64.b64encode(image).decode()}"
        try:
            resp = await asyncio.wait_for(self.client.chat.completions.create(
                model=self.model, response_format={"type": "json_object"},
                messages=[{"role": "system", "content": SYSTEM_PROMPT},
                          {"role": "user", "content": [{"type": "text", "text": user_prompt(crop_name)},
                                                       {"type": "image_url", "image_url": {"url": data_url}}]}]),
                timeout=self.timeout)
            text = resp.choices[0].message.content or ""
        except TimeoutError as exc:
            raise GradingProviderError("timeout", self.name) from exc
        except Exception as exc:
            log.warning("openai_call_failed", error_type=type(exc).__name__)
            raise GradingProviderError("api_error", self.name) from exc
        return parse_raw_grading(text, self.name)
