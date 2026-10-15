"""Market reports: ingestion, retrieval, embedding (pgvector) and semantic search with a keyword fallback."""
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import transactional
from app.core.logging import get_logger
from app.models.market_report import MarketReport
from app.models.user import User
from app.repositories.market import MarketRepository
from app.schemas.market import MarketReportIn, MarketReportOut, MarketSearchHit, MarketSearchOut
from app.services.audit import Actor, AuditService, RequestContext
from app.services.embedding import EmbeddingProvider, EmbeddingProviderError
from app.utils.crops import crop_or_title, find_crop_in_text
from app.utils.money import paise_to_rupees, rupees_to_paise
from app.utils.time import utcnow

log = get_logger(__name__)


def report_text(r: MarketReport) -> str:
    return (f"{r.crop} price at {r.market}, {r.location} on {r.report_date.isoformat()}: average Rs {paise_to_rupees(r.average_price_paise)} "
            f"per kg, range Rs {paise_to_rupees(r.min_price_paise)} to Rs {paise_to_rupees(r.max_price_paise)}. Source: {r.source}"
            + (" (sample data)" if r.is_sample else ""))


def report_out(r: MarketReport) -> MarketReportOut:
    return MarketReportOut(id=r.id, crop=r.crop, location=r.location, market=r.market,
                           min_price=paise_to_rupees(r.min_price_paise), max_price=paise_to_rupees(r.max_price_paise),
                           average_price=paise_to_rupees(r.average_price_paise), report_date=r.report_date,
                           source=r.source, is_sample=r.is_sample)


class MarketService:
    def __init__(self, session: AsyncSession, embedder: EmbeddingProvider) -> None:
        self.session, self.embedder = session, embedder
        self.repo, self.audit = MarketRepository(session), AuditService(session)

    async def upsert(self, admin: User, reports: list[MarketReportIn], ctx: RequestContext) -> int:
        rows = [{"crop": crop_or_title(r.crop), "location": r.location, "market": r.market,
                 "min_price_paise": rupees_to_paise(r.min_price), "max_price_paise": rupees_to_paise(r.max_price),
                 "average_price_paise": rupees_to_paise(r.average_price), "report_date": r.report_date,
                 "source": r.source, "is_sample": r.is_sample} for r in reports]
        # de-duplicate on the natural key inside one batch (ON CONFLICT cannot touch a row twice)
        rows = list({(r["crop"], r["market"], r["report_date"], r["source"]): r for r in rows}.values())
        async with transactional(self.session):
            n = await self.repo.upsert_many(rows)
            self.audit.record(action="market.reports_upserted", entity_type="market_report",
                              actor=Actor(admin.id, admin.role), ip=ctx.ip,
                              metadata={"count": n, "crops": sorted({r["crop"] for r in rows}),
                                        "sample": any(r["is_sample"] for r in rows)})
        return n

    async def prices(self, *, crop: str | None, location: str | None, days: int, limit: int) -> list[MarketReport]:
        return await self.repo.list_reports(crop=crop_or_title(crop) if crop else None, location=location,
                                    since=utcnow().date() - timedelta(days=days), limit=limit)

    async def latest(self, crop: str, location: str | None) -> MarketReport | None:
        canon = crop_or_title(crop)
        rows = await self.repo.list_reports(crop=canon, location=location, limit=1) if location else []
        return rows[0] if rows else next(iter(await self.repo.list_reports(crop=canon, limit=1)), None)

    async def embed_pending(self, limit: int = 50) -> int:
        """Embeds reports lacking a vector for the CURRENT provider model. Raises EmbeddingProviderError (job retries)."""
        pending = await self.repo.missing_embeddings(self.embedder.model_id, limit)
        if not pending:
            return 0
        vecs = await self.embedder.embed_documents([report_text(r) for r in pending])
        async with transactional(self.session):
            for r, v in zip(pending, vecs, strict=True):
                r.embedding, r.embedding_model = v, self.embedder.model_id
        return len(pending)

    async def search(self, query: str, k: int, *, crop: str | None = None, location: str | None = None) -> MarketSearchOut:
        canon = crop_or_title(crop) if crop else find_crop_in_text(query)
        try:
            vec = await self.embedder.embed_query(query)
            hits = await self.repo.semantic(vec, self.embedder.model_id, k, crop=canon, location=location)
            if hits:
                return MarketSearchOut(mode="semantic", crop=canon, hits=[
                    MarketSearchHit(report=report_out(r), similarity=round(s, 4)) for r, s in hits])
        except EmbeddingProviderError as exc:
            log.warning("semantic_search_degraded", kind=exc.kind)
        rows = await self.repo.keyword(crop=canon, location=location, k=k)  # deterministic fallback
        return MarketSearchOut(mode="keyword", crop=canon, hits=[MarketSearchHit(report=report_out(r)) for r in rows])
