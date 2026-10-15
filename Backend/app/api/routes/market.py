from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import (
    CurrentUser,
    RequestContextDep,
    SessionDep,
    get_embedding_provider,
    get_job_queue,
    require_roles,
)
from app.core.errors import NotFoundError
from app.core.rate_limit import rate_limit
from app.models.enums import Grade, UserRole
from app.schemas.common import Envelope
from app.schemas.market import (
    MarketReportOut,
    MarketReportsUpsert,
    MarketSearchOut,
    UpsertResult,
)
from app.schemas.pricing import PricingOut
from app.services.embedding import EmbeddingProvider
from app.services.market import MarketService, report_out
from app.services.pricing import PricingService, to_out
from app.workers.queue import JobQueue

router = APIRouter(prefix="/market", tags=["market"])
Admin = Depends(require_roles(UserRole.ADMIN))
Embedder = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]
Queue = Annotated[JobQueue, Depends(get_job_queue)]


@router.get("/prices", response_model=Envelope[list[MarketReportOut]])
async def prices(_: CurrentUser, session: SessionDep, embedder: Embedder, crop: str | None = Query(None, max_length=120),
                 location: str | None = Query(None, max_length=200), days: int = Query(30, ge=1, le=365),
                 limit: int = Query(100, ge=1, le=500)):
    rows = await MarketService(session, embedder).prices(crop=crop, location=location, days=days, limit=limit)
    return Envelope(data=[report_out(r) for r in rows])


@router.get("/latest", response_model=Envelope[MarketReportOut])
async def latest(_: CurrentUser, session: SessionDep, embedder: Embedder, crop: str = Query(min_length=2, max_length=120),
                 location: str | None = Query(None, max_length=200)):
    r = await MarketService(session, embedder).latest(crop, location)
    if r is None:
        raise NotFoundError("No market data for this crop")
    return Envelope(data=report_out(r))


@router.get("/search", response_model=Envelope[MarketSearchOut],
            dependencies=[Depends(rate_limit("market_search", 30, 60, per_user=True))])
async def search(_: CurrentUser, session: SessionDep, embedder: Embedder, q: str = Query(min_length=2, max_length=300),
                 k: int = Query(5, ge=1, le=10), crop: str | None = Query(None, max_length=120),
                 location: str | None = Query(None, max_length=200)):
    return Envelope(data=await MarketService(session, embedder).search(q, k, crop=crop, location=location))


@router.get("/price-recommendation", response_model=Envelope[PricingOut])
async def price_recommendation(_: CurrentUser, session: SessionDep, crop: str = Query(min_length=2, max_length=120),
                               location: str | None = Query(None, max_length=200), grade: Grade | None = None,
                               quantity_kg: Decimal = Query(Decimal(100), gt=0, le=1_000_000)):
    """Deterministic recommendation for ad-hoc queries. Listing-bound recommendations (Smart Pricing Agent) come in Stage 10."""
    return Envelope(data=to_out(await PricingService(session).recommend(
        crop=crop, location=location, grade=grade, quantity_kg=quantity_kg)))


@router.post("/reports", response_model=Envelope[UpsertResult], dependencies=[Admin], status_code=201)
async def upsert_reports(body: MarketReportsUpsert, admin: CurrentUser, session: SessionDep, embedder: Embedder,
                         ctx: RequestContextDep, queue: Queue):
    n = await MarketService(session, embedder).upsert(admin, body.reports, ctx)
    try:  # enqueue only after commit; ingestion must not fail if the queue is down (backfill endpoint exists)
        await queue.enqueue("embed_market_reports_job")
        queued = True
    except Exception:
        queued = False
    return Envelope(data=UpsertResult(upserted=n, embedding_job_queued=queued))


@router.post("/reports/embed", response_model=Envelope[UpsertResult], dependencies=[Admin])
async def trigger_embedding(queue: Queue):
    await queue.enqueue("embed_market_reports_job")
    return Envelope(data=UpsertResult(upserted=0, embedding_job_queued=True))
