import asyncio
from typing import Any

from openai import AsyncOpenAI

from app.core.config import Settings
from app.core.logging import get_logger
from app.integrations.stt import SpeechProviderError, SpokenAudio

log = get_logger(__name__)


class OpenAISpeech:
    """Optional spoken answer. Disabled unless OPENAI_TTS_MODEL and OPENAI_TTS_VOICE are configured."""
    name = "openai"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.model, self.voice, self.timeout = settings.OPENAI_TTS_MODEL, settings.OPENAI_TTS_VOICE, settings.AI_PROVIDER_TIMEOUT_SECONDS
        key = settings.OPENAI_API_KEY.get_secret_value()
        self.client: Any = client or (AsyncOpenAI(api_key=key, timeout=self.timeout) if (key and self.model and self.voice) else None)

    @property
    def available(self) -> bool:
        return self.client is not None

    async def synthesize(self, text: str, language: str) -> SpokenAudio:
        if not self.available:
            raise SpeechProviderError("not_configured", self.name)
        try:
            resp = await asyncio.wait_for(self.client.audio.speech.create(
                model=self.model, voice=self.voice, input=text, response_format="mp3"), self.timeout)
            data = resp.content if hasattr(resp, "content") else await resp.aread()
        except TimeoutError as exc:
            raise SpeechProviderError("timeout", self.name) from exc
        except Exception as exc:
            log.warning("openai_tts_failed", error_type=type(exc).__name__)
            raise SpeechProviderError("api_error", self.name) from exc
        if not data:
            raise SpeechProviderError("invalid_response", self.name)
        return SpokenAudio(data=data, mime="audio/mpeg", provider=self.name)
