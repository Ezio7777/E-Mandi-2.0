import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Lang = Literal["en", "hi", "kn"]
SESSION_ID_RX = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _check_session(v: str | None) -> str | None:
    if v is not None and not SESSION_ID_RX.match(v):
        raise ValueError("session_id must be 8-64 characters: letters, digits, '_' or '-'")
    return v


class VoiceTextIn(BaseModel):
    """A typed question (the same pipeline as audio, minus transcription)."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=2000)  # service enforces VOICE_MAX_TEXT_CHARS (configurable)
    language: Lang | None = None  # requested ANSWER language; default = language detected from the question
    session_id: str | None = None
    speak: bool = False

    _s = field_validator("session_id")(_check_session)


class SourceOut(BaseModel):
    type: Literal["market_report", "pricing", "listing", "inventory"]
    title: str
    detail: str
    date: str | None = None
    is_sample: bool = False


class ToolCallOut(BaseModel):
    tool: str
    ok: bool
    rows: int
    ms: int


class AudioOut(BaseModel):
    mime: str
    data_base64: str
    provider: str


class VoiceAnswerOut(BaseModel):
    session_id: str
    transcript: str
    language: Lang                     # language of the ANSWER
    detected_language: Lang            # language of the question
    intent: str
    outcome: Literal["answered", "needs_info", "refused", "no_data", "unknown"]
    answer: str
    sources: list[SourceOut]
    tool_calls: list[ToolCallOut]
    audio: AudioOut | None = None
    transcription_provider: str | None = None
    answer_provider: Literal["deterministic", "gemini", "openai"] = "deterministic"
    degraded: list[str] = []           # e.g. ["tts_unavailable", "llm_unavailable"] - the answer is still correct
    execution_id: str


class VoiceTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str


class VoiceSessionOut(BaseModel):
    session_id: str
    turns: list[VoiceTurn]
    crop: str | None
    city: str | None
