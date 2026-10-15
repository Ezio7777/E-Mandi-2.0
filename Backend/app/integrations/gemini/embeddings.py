import asyncio
from typing import Any

from google import genai
from google.genai import types

from app.core.config import Settings
from app.core.logging import get_logger

log = get_logger(__name__)


class EmbeddingProviderError(Exception):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class GeminiEmbeddingProvider:
    """Semantic embeddings. Model name and dimension come from configuration only."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.model, self.dim = settings.GEMINI_EMBEDDING_MODEL, settings.EMBEDDING_DIM
        self.timeout = settings.AI_PROVIDER_TIMEOUT_SECONDS
        key = settings.GEMINI_API_KEY.get_secret_value()
        self._configured = bool(key and self.model)
        self.client: Any = client or (genai.Client(api_key=key) if self._configured else None)
        self.model_id = f"gemini:{self.model}:{self.dim}"

    @property
    def available(self) -> bool:
        return self.client is not None

    async def _embed(self, texts: list[str], task: str) -> list[list[float]]:
        if not self.available:
            raise EmbeddingProviderError("not_configured")
        try:
            resp = await asyncio.wait_for(self.client.aio.models.embed_content(
                model=self.model, contents=texts,
                config=types.EmbedContentConfig(task_type=task, output_dimensionality=self.dim)), self.timeout)
        except TimeoutError as exc:
            raise EmbeddingProviderError("timeout") from exc
        except Exception as exc:
            log.warning("gemini_embed_failed", error_type=type(exc).__name__)
            raise EmbeddingProviderError("api_error") from exc
        vecs = [list(e.values) for e in (resp.embeddings or [])]
        if len(vecs) != len(texts) or any(len(v) != self.dim for v in vecs):
            raise EmbeddingProviderError("invalid_response")  # wrong count/dimension would corrupt the index
        return vecs

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts, "RETRIEVAL_DOCUMENT")

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text], "RETRIEVAL_QUERY"))[0]
