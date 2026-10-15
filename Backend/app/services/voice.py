"""Voice Assistant orchestration: audio -> transcript -> LangGraph agent -> answer (+ optional speech).

Audio is validated by magic bytes, processed in memory and never stored. Each request is a tracked AgentExecution
(VOICE_ASSISTANT) holding only operational metadata: intent, outcome, tool calls, provider - NOT the transcript or answer.
Transcripts/answers live only in the short-lived Redis session of the asking user."""
import base64
import uuid
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runtime import AgentExecutionService, AgentOutcome, run_tracked
from app.agents.tools.readonly import ToolBelt
from app.agents.voice_graph import VoiceAssistantAgent, VoiceState
from app.core.config import Settings
from app.core.database import transactional
from app.core.errors import AppError, DomainValidationError
from app.core.logging import get_logger
from app.integrations.gemini.text import GeminiTextLLM
from app.integrations.gemini.transcription import GeminiTranscriber
from app.integrations.llm_common import TextLLM
from app.integrations.openai.text import OpenAITextLLM
from app.integrations.openai.transcription import OpenAITranscriber
from app.integrations.openai.tts import OpenAISpeech
from app.integrations.stt import SpeechToText, TextToSpeech, transcribe_with_fallback
from app.models.enums import AgentName, AgentStatus
from app.models.user import User
from app.schemas.voice import AudioOut, SourceOut, ToolCallOut, VoiceAnswerOut, VoiceSessionOut, VoiceTurn
from app.services.embedding import EmbeddingProvider
from app.services.voice_session import VoiceSessionStore
from app.utils.audio import InvalidAudio, sniff_audio

log = get_logger(__name__)


class AudioTooLargeError(AppError):
    status_code, code, message = 413, "audio_too_large", "Audio is too large"


class UnsupportedAudioError(AppError):
    status_code, code, message = 415, "unsupported_audio", "Unsupported audio format"


class TranscriptionUnavailableError(AppError):
    status_code, code, message = 503, "transcription_unavailable", "Speech recognition is unavailable right now. Please type your question instead."


@dataclass
class VoiceProviders:
    stt: list[SpeechToText]
    tts: TextToSpeech | None
    llms: list[TextLLM]


def build_voice_providers(settings: Settings) -> VoiceProviders:
    """Gemini first, OpenAI fallback (same policy as grading/pricing). Providers that aren't configured are inert."""
    return VoiceProviders(stt=[GeminiTranscriber(settings), OpenAITranscriber(settings)], tts=OpenAISpeech(settings),
                          llms=[GeminiTextLLM(settings), OpenAITextLLM(settings)])


class VoiceService:
    def __init__(self, session: AsyncSession, redis: Redis | None, settings: Settings, embedder: EmbeddingProvider,
                 providers: VoiceProviders) -> None:
        self.session, self.settings, self.embedder, self.providers = session, settings, embedder, providers
        self.store = VoiceSessionStore(redis, settings)

    # ------------------------------------------------------------------ entry points
    async def ask_text(self, user: User, text: str, language: str | None, session_id: str | None, speak: bool) -> VoiceAnswerOut:
        text = text.strip()
        if not text:
            raise DomainValidationError("Question cannot be empty")
        if len(text) > self.settings.VOICE_MAX_TEXT_CHARS:
            raise DomainValidationError(f"Question is too long (max {self.settings.VOICE_MAX_TEXT_CHARS} characters)")
        return await self._answer(user, text, language, session_id, speak, "voice.text_received", None, False)

    async def ask_audio(self, user: User, audio: bytes, language: str | None, session_id: str | None, speak: bool) -> VoiceAnswerOut:
        if not audio:
            raise DomainValidationError("Audio is empty")
        if len(audio) > self.settings.VOICE_MAX_AUDIO_BYTES:
            raise AudioTooLargeError(f"Audio is too large (max {self.settings.VOICE_MAX_AUDIO_BYTES // 1024} KB)")
        try:
            mime, _ext = sniff_audio(audio)
        except InvalidAudio as exc:
            raise UnsupportedAudioError(str(exc)) from exc
        res = await transcribe_with_fallback(self.providers.stt, audio, mime, language)
        if res.transcript is None:
            log.warning("voice_transcription_failed", errors=res.errors)
            raise TranscriptionUnavailableError()
        text = res.transcript.text.strip()[: self.settings.VOICE_MAX_TEXT_CHARS]
        return await self._answer(user, text, language, session_id, speak, "voice.audio_received", res.transcript.provider, res.fallback_used)

    # ------------------------------------------------------------------ core
    async def _answer(self, user: User, text: str, language: str | None, session_id: str | None, speak: bool, trigger: str,
                      stt_provider: str | None, stt_fallback: bool) -> VoiceAnswerOut:
        uid, role = user.id, user.role
        sess = await self.store.load(uid, session_id)
        async with transactional(self.session):
            ex, _ = await AgentExecutionService(self.session).queue(AgentName.VOICE_ASSISTANT, trigger, entity_type="user", entity_id=uid)
        belt = ToolBelt(self.session, self.embedder, self.settings, uid, role)
        agent = VoiceAssistantAgent(belt, self.providers.llms, self.settings)
        holder: dict[str, VoiceState] = {}

        async def fn() -> AgentOutcome:
            st = await agent.run(text, hint_lang=language, requested_lang=language, session=sess)
            holder["st"] = st
            degraded = bool(st.get("degraded"))
            status = AgentStatus.COMPLETED
            return AgentOutcome(status, f"{st['parsed'].intent.value} -> {st['outcome']}", st.get("answer_provider", "deterministic"),
                                stt_fallback or degraded, belt.calls)

        await run_tracked(self.session, ex.id, fn, attempt=1, max_attempts=1)
        st = holder["st"]
        answer, lang = st["answer"], st["lang"]
        degraded = list(dict.fromkeys(st.get("degraded", [])))

        audio_out: AudioOut | None = None
        if speak:
            tts = self.providers.tts
            if tts is not None and tts.available and len(answer) <= self.settings.VOICE_TTS_MAX_CHARS:
                try:
                    sp = await tts.synthesize(answer, lang)
                    audio_out = AudioOut(mime=sp.mime, data_base64=base64.b64encode(sp.data).decode(), provider=sp.provider)
                except Exception as exc:
                    log.warning("voice_tts_failed", error_type=type(exc).__name__)
            if audio_out is None:
                degraded.append("tts_unavailable")

        sess.crop, sess.city = st.get("crop") or sess.crop, st.get("city") or sess.city
        await self.store.save(uid, sess, text, answer)
        return VoiceAnswerOut(
            session_id=sess.session_id, transcript=text, language=lang, detected_language=st["detected"],  # type: ignore[arg-type]
            intent=st["parsed"].intent.value, outcome=st["outcome"],  # type: ignore[arg-type]
            answer=answer, sources=[SourceOut(**s) for s in st.get("sources", [])],
            tool_calls=[ToolCallOut(tool=c["tool"], ok=c["ok"], rows=c["rows"], ms=c["ms"]) for c in belt.calls],
            audio=audio_out, transcription_provider=stt_provider, answer_provider=st.get("answer_provider", "deterministic"),  # type: ignore[arg-type]
            degraded=degraded, execution_id=str(ex.id))

    # ------------------------------------------------------------------ session
    async def history(self, user: User, session_id: str) -> VoiceSessionOut | None:
        st = await self.store.get(user.id, session_id)
        if st is None:
            return None
        return VoiceSessionOut(session_id=session_id, turns=[VoiceTurn(**t) for t in st.turns], crop=st.crop, city=st.city)  # type: ignore[arg-type]

    async def clear(self, user: User, session_id: str) -> None:
        await self.store.delete(user.id, session_id)


_ = uuid
