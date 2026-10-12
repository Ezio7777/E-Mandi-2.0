"""arq job: embed market reports that lack a vector for the current provider model. Retried on provider failure."""
from typing import Any

from arq import Retry

from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.core.logging import get_logger
from app.services.embedding import EmbeddingProviderError, build_embedding_provider
from app.services.market import MarketService

log = get_logger(__name__)


async def embed_market_reports_job(ctx: dict[str, Any]) -> int:
    embedder = ctx.get("embedder") or build_embedding_provider(get_settings())
    total = 0
    async with get_sessionmaker()() as session:
        svc = MarketService(session, embedder)
        try:
            for _ in range(20):  # bounded: at most 20 batches per run
                n = await svc.embed_pending(50)
                total += n
                if n == 0:
                    break
        except EmbeddingProviderError as exc:
            log.warning("embedding_retry", kind=exc.kind, embedded_so_far=total)
            raise Retry(defer=int(ctx.get("job_try", 1)) * 30) from exc
    return total
