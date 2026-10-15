"""Embedding provider abstraction. Swap providers via EMBEDDING_PROVIDER; vectors are tagged with model_id so
embeddings from different providers are never compared with each other."""
import hashlib
import itertools
import math
import re
from typing import Protocol

from app.core.config import Settings
from app.integrations.gemini.embeddings import EmbeddingProviderError, GeminiEmbeddingProvider
from app.utils.crops import normalize_text

__all__ = ["EmbeddingProvider", "EmbeddingProviderError", "HashEmbeddingProvider", "build_embedding_provider"]


class EmbeddingProvider(Protocol):
    model_id: str
    dim: int

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...


class HashEmbeddingProvider:
    """Offline, deterministic, zero-cost. Hashed bag of words + bigrams (LEXICAL similarity, not semantic).
    Good enough for dev/tests and as a no-cost default; use gemini for real semantic retrieval."""

    def __init__(self, dim: int) -> None:
        self.dim, self.model_id = dim, f"hash-v1:{dim}"

    def _vec(self, text: str) -> list[float]:
        toks = re.findall(r"\w+", normalize_text(text))
        feats = toks + [f"{a}_{b}" for a, b in itertools.pairwise(toks)]
        v = [0.0] * self.dim
        for f in feats:
            h = hashlib.sha1(f.encode(), usedforsecurity=False).digest()  # feature hashing, not security
            v[int.from_bytes(h[:4], "big") % self.dim] += 1.0 if h[4] % 2 else -1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.EMBEDDING_PROVIDER == "gemini":
        return GeminiEmbeddingProvider(settings)
    return HashEmbeddingProvider(settings.EMBEDDING_DIM)
