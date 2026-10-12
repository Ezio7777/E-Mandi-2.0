"""Speech-to-text / text-to-speech contracts. Providers are interchangeable; model names are configuration only.
Audio is processed in memory: it is never written to disk or object storage."""
from dataclasses import dataclass
from typing import Protocol

from app.core.logging import get_logger

log = get_logger(__name__)


class SpeechProviderError(Exception):
    """kind: timeout | api_error | invalid_response | not_configured"""

    def __init__(self, kind: str, provider: str) -> None:
        super().__init__(f"{provider}:{kind}")
        self.kind, self.provider = kind, provider


@dataclass
class Transcript:
    text: str
    provider: str
    language: str | None = None  # provider-reported ISO code if any (we re-detect deterministically anyway)


class SpeechToText(Protocol):
    name: str

    @property
    def available(self) -> bool: ...

    async def transcribe(self, audio: bytes, mime: str, language_hint: str | None) -> Transcript: ...


@dataclass
class SpokenAudio:
    data: bytes
    mime: str
    provider: str


class TextToSpeech(Protocol):
    name: str

    @property
    def available(self) -> bool: ...

    async def synthesize(self, text: str, language: str) -> SpokenAudio: ...


@dataclass
class TranscriptionResult:
    transcript: Transcript | None
    fallback_used: bool
    errors: list[str]


async def transcribe_with_fallback(providers: list[SpeechToText], audio: bytes, mime: str, hint: str | None) -> TranscriptionResult:
    """Gemini-first / OpenAI-fallback (order is the caller's). A provider returning empty text counts as a failure."""
    errors: list[str] = []
    for p in providers:
        if not p.available:
            continue
        try:
            t = await p.transcribe(audio, mime, hint)
            if t.text.strip():
                return TranscriptionResult(t, bool(errors), errors)
            errors.append(f"{p.name}:empty")
        except SpeechProviderError as exc:
            errors.append(f"{exc.provider}:{exc.kind}")
            log.warning("stt_failed", provider=exc.provider, kind=exc.kind)
    return TranscriptionResult(None, bool(errors), errors)
