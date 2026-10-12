"""Short-lived conversation state in Redis. Keyed by (user_id, session_id): a session id alone can never read another
user's conversation. Holds the last few turns + the resolved crop/city so follow-ups ("and in Mysuru?") work.
Everything expires (VOICE_SESSION_TTL_SECONDS); nothing here is written to Postgres."""
import json
import re
import secrets
import uuid
from dataclasses import dataclass, field

from redis.asyncio import Redis

from app.core.config import Settings
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class SessionState:
    session_id: str
    turns: list[dict[str, str]] = field(default_factory=list)  # [{"role": "user"|"assistant", "text": "..."}]
    crop: str | None = None
    city: str | None = None


class VoiceSessionStore:
    def __init__(self, redis: Redis | None, settings: Settings) -> None:
        self.redis, self.ttl, self.max_turns = redis, settings.VOICE_SESSION_TTL_SECONDS, settings.VOICE_SESSION_MAX_TURNS

    @staticmethod
    def new_id() -> str:
        return secrets.token_urlsafe(16)

    @staticmethod
    def _key(user_id: uuid.UUID, session_id: str) -> str:
        return f"voice:s:{user_id}:{session_id}"

    async def load(self, user_id: uuid.UUID, session_id: str | None) -> SessionState:
        sid = session_id or self.new_id()
        if self.redis is None or session_id is None:
            return SessionState(sid)
        try:
            raw = await self.redis.get(self._key(user_id, sid))
            if raw:
                d = json.loads(raw)
                return SessionState(sid, list(d.get("turns", [])), d.get("crop"), d.get("city"))
        except Exception as exc:  # noqa: BLE001 - the assistant still works statelessly if Redis hiccups
            log.warning("voice_session_load_failed", error_type=type(exc).__name__)
        return SessionState(sid)

    async def save(self, user_id: uuid.UUID, st: SessionState, user_text: str, answer: str) -> None:
        if self.redis is None:
            return
        st.turns = (st.turns + [{"role": "user", "text": user_text}, {"role": "assistant", "text": answer}])[-2 * self.max_turns:]
        try:
            await self.redis.set(self._key(user_id, st.session_id),
                                 json.dumps({"turns": st.turns, "crop": st.crop, "city": st.city}, ensure_ascii=False), ex=self.ttl)
        except Exception as exc:  # noqa: BLE001
            log.warning("voice_session_save_failed", error_type=type(exc).__name__)

    async def get(self, user_id: uuid.UUID, session_id: str) -> SessionState | None:
        if self.redis is None:
            return None
        raw = await self.redis.get(self._key(user_id, session_id))
        if not raw:
            return None
        d = json.loads(raw)
        return SessionState(session_id, list(d.get("turns", [])), d.get("crop"), d.get("city"))

    async def delete(self, user_id: uuid.UUID, session_id: str) -> None:
        if self.redis is not None:
            await self.redis.delete(self._key(user_id, session_id))


_ = re
