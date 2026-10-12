import re
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.core.config import Settings
from app.core.dependencies import CurrentUser, RedisDep, SessionDep, SettingsDep, get_embedding_provider, get_voice_providers
from app.core.errors import DomainValidationError, NotFoundError
from app.core.rate_limit import rate_limit
from app.schemas.common import Envelope
from app.schemas.voice import SESSION_ID_RX, Lang, VoiceAnswerOut, VoiceSessionOut, VoiceTextIn
from app.services.embedding import EmbeddingProvider
from app.services.voice import AudioTooLargeError, VoiceProviders, VoiceService

router = APIRouter(prefix="/voice", tags=["voice"])
SID = re.compile(SESSION_ID_RX.pattern)


def _svc(session: SessionDep, redis: RedisDep, settings: SettingsDep, embedder: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
         providers: Annotated[VoiceProviders, Depends(get_voice_providers)]) -> VoiceService:
    return VoiceService(session, redis, settings, embedder, providers)


Svc = Annotated[VoiceService, Depends(_svc)]


def _sid(v: str) -> str:
    if not SID.match(v):
        raise NotFoundError("Voice session not found")
    return v


@router.post("/query", response_model=Envelope[VoiceAnswerOut], dependencies=[Depends(rate_limit("voice_text", 30, 60, per_user=True))])
async def ask_text(body: VoiceTextIn, user: CurrentUser, svc: Svc):
    """Typed question through the same agent pipeline as audio (accessibility + clients without a microphone)."""
    return Envelope(data=await svc.ask_text(user, body.text, body.language, body.session_id, body.speak))


@router.post("/audio", response_model=Envelope[VoiceAnswerOut], dependencies=[Depends(rate_limit("voice_audio", 15, 60, per_user=True))])
async def ask_audio(user: CurrentUser, svc: Svc, settings: SettingsDep, audio: Annotated[UploadFile, File()],
                    language: Annotated[Lang | None, Form()] = None, session_id: Annotated[str | None, Form()] = None,
                    speak: Annotated[bool, Form()] = False):
    """multipart/form-data: audio (WAV/MP3/M4A/OGG/WebM/FLAC, <= VOICE_MAX_AUDIO_BYTES). Processed in memory only."""
    if session_id is not None and not SID.match(session_id):
        raise DomainValidationError("session_id must be 8-64 characters: letters, digits, '_' or '-'")
    data = await audio.read(settings.VOICE_MAX_AUDIO_BYTES + 1)  # bounded read: never buffer an unbounded upload
    if len(data) > settings.VOICE_MAX_AUDIO_BYTES:
        raise AudioTooLargeError(f"Audio is too large (max {settings.VOICE_MAX_AUDIO_BYTES // 1024} KB)")
    return Envelope(data=await svc.ask_audio(user, data, language, session_id, speak))


@router.get("/sessions/{session_id}", response_model=Envelope[VoiceSessionOut])
async def get_session(session_id: str, user: CurrentUser, svc: Svc):
    st = await svc.history(user, _sid(session_id))
    if st is None:
        raise NotFoundError("Voice session not found")  # same answer for 'expired' and 'someone else's'
    return Envelope(data=st)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_session(session_id: str, user: CurrentUser, svc: Svc) -> None:
    await svc.clear(user, _sid(session_id))


_ = Settings
