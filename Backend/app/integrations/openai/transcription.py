import asyncio
from typing import Any

from openai import AsyncOpenAI

from app.core.config import Settings
from app.core.logging import get_logger
from app.integrations.stt import SpeechProviderError, Transcript

log = get_logger(__name__)
_EXT = {"audio/wav": "wav", "audio/ogg": "ogg", "audio/webm": "webm", "audio/flac": "flac", "audio/mp4": "m4a", "audio/mpeg": "mp3"}


class OpenAITranscriber:
    name = "openai"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.model, self.timeout = settings.OPENAI_TRANSCRIPTION_MODEL, settings.AI_PROVIDER_TIMEOUT_SECONDS
        key = settings.OPENAI_API_KEY.get_secret_value()
        self.client: Any = client or (AsyncOpenAI(api_key=key, timeout=self.timeout) if (key and self.model) else None)

    @property
    def available(self) -> bool:
        return self.client is not None

    async def transcribe(self, audio: bytes, mime: str, language_hint: str | None) -> Transcript:
        if not self.available:
            raise SpeechProviderError("not_configured", self.name)
        kwargs: dict[str, Any] = {"model": self.model, "file": (f"audio.{_EXT.get(mime, 'bin')}", audio, mime)}
        if language_hint in ("en", "hi", "kn"):
            kwargs["language"] = language_hint
        try:
            resp = await asyncio.wait_for(self.client.audio.transcriptions.create(**kwargs), self.timeout)
        except TimeoutError as exc:
            raise SpeechProviderError("timeout", self.name) from exc
        except Exception as exc:
            log.warning("openai_transcription_failed", error_type=type(exc).__name__)
            raise SpeechProviderError("api_error", self.name) from exc
        text = getattr(resp, "text", None)
        if not isinstance(text, str):
            raise SpeechProviderError("invalid_response", self.name)
        return Transcript(text=text.strip(), provider=self.name, language=getattr(resp, "language", None))
