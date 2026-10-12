import math
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.integrations.gemini.embeddings import EmbeddingProviderError, GeminiEmbeddingProvider
from app.services.embedding import HashEmbeddingProvider, build_embedding_provider
from app.utils.crops import canonical_crop, crop_or_title, find_crop_in_text

S = Settings(ENVIRONMENT="test", JWT_SECRET="x" * 40, EMBEDDING_DIM=64, AI_PROVIDER_TIMEOUT_SECONDS=0.1,
             GEMINI_API_KEY="k", GEMINI_EMBEDDING_MODEL="emb-model")


def cos(a, b):
    return sum(x * y for x, y in zip(a, b))


async def test_hash_embedding_properties():
    p = HashEmbeddingProvider(64)
    a, b, c = await p.embed_documents(["tomato price bengaluru", "tomato price bengaluru", "wheat rate delhi mandi"])
    assert a == b and len(a) == 64 and math.isclose(cos(a, a), 1.0, rel_tol=1e-6)
    q = await p.embed_query("tomato bengaluru")
    assert cos(q, a) > cos(q, c) and p.model_id == "hash-v1:64"


def test_provider_selection():
    assert isinstance(build_embedding_provider(S), HashEmbeddingProvider)
    g = build_embedding_provider(S.model_copy(update={"EMBEDDING_PROVIDER": "gemini"}))
    assert g.model_id == "gemini:emb-model:64"  # model + dim tag: vectors from different models never mix


class FakeClient:
    def __init__(self, vecs=None, exc=None, sleep=False):
        self.calls = []
        self.aio = SimpleNamespace(models=SimpleNamespace(embed_content=self._e))
        self.vecs, self.exc, self.sleep = vecs, exc, sleep

    async def _e(self, **kw):
        self.calls.append(kw)
        if self.sleep:
            import asyncio
            await asyncio.sleep(3)
        if self.exc:
            raise self.exc
        return SimpleNamespace(embeddings=[SimpleNamespace(values=v) for v in self.vecs])


async def test_gemini_embeddings_ok_and_request_shape():
    c = FakeClient([[0.1] * 64, [0.2] * 64])
    out = await GeminiEmbeddingProvider(S, client=c).embed_documents(["a", "b"])
    assert len(out) == 2 and c.calls[0]["model"] == "emb-model"
    assert c.calls[0]["config"].output_dimensionality == 64 and c.calls[0]["config"].task_type == "RETRIEVAL_DOCUMENT"


@pytest.mark.parametrize("client", [
    FakeClient([[0.1] * 10]), FakeClient([]), FakeClient(exc=RuntimeError("503")), FakeClient(sleep=True)])
async def test_gemini_embedding_failures_are_typed(client):
    with pytest.raises(EmbeddingProviderError):
        await GeminiEmbeddingProvider(S, client=client).embed_query("x")


async def test_gemini_embedding_not_configured():
    p = GeminiEmbeddingProvider(Settings(ENVIRONMENT="test", JWT_SECRET="x" * 40))
    with pytest.raises(EmbeddingProviderError) as e:
        await p.embed_query("x")
    assert e.value.kind == "not_configured"


@pytest.mark.parametrize(("text", "crop"), [
    ("tamatar", "Tomato"), ("टमाटर", "Tomato"), ("ಟೊಮೇಟೊ", "Tomato"), ("PYAZ", "Onion"), ("ಈರುಳ್ಳಿ", "Onion"),
    ("aloo", "Potato"), ("mirchi", "Chilli"), ("gehun", "Wheat"), ("ragi", "Ragi"), ("unknown crop", None)])
def test_canonical_crop(text, crop):
    assert canonical_crop(text) == crop


def test_find_crop_in_text_and_fallback_title():
    assert find_crop_in_text("Bhai, aaj Bangalore mein tamatar ka kya bhav hai?") == "Tomato"
    assert find_crop_in_text("ಇಂದು ಈರುಳ್ಳಿ ಬೆಲೆ ಎಷ್ಟು") == "Onion"
    assert find_crop_in_text("price of patta gobhi today") == "Cabbage"
    assert find_crop_in_text("what is the weather") is None
    assert crop_or_title("  dragon   fruit ") == "Dragon Fruit" and crop_or_title("TOMATOES") == "Tomato"
