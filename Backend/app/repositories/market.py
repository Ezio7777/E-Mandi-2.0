import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market_report import MarketReport


class MarketRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_many(self, rows: Sequence[dict[str, Any]]) -> int:
        """Idempotent on the natural key. Changed rows lose their embedding so they get re-embedded."""
        if not rows:
            return 0
        stmt = pg_insert(MarketReport).values(list(rows))
        stmt = stmt.on_conflict_do_update(
            constraint="uq_market_reports_natural",
            set_={"location": stmt.excluded.location, "min_price_paise": stmt.excluded.min_price_paise,
                  "max_price_paise": stmt.excluded.max_price_paise, "average_price_paise": stmt.excluded.average_price_paise,
                  "is_sample": stmt.excluded.is_sample, "embedding": None, "embedding_model": None,
                  "updated_at": func.now()})
        await self.session.execute(stmt)
        return len(rows)

    async def list_reports(self, *, crop: str | None = None, location: str | None = None, since: date | None = None,
                   limit: int = 200) -> list[MarketReport]:
        stmt = select(MarketReport)
        if crop:
            stmt = stmt.where(func.lower(MarketReport.crop) == crop.lower())
        if location:
            stmt = stmt.where(func.lower(MarketReport.location) == location.lower())
        if since:
            stmt = stmt.where(MarketReport.report_date >= since)
        return list((await self.session.scalars(stmt.order_by(MarketReport.report_date.desc(), MarketReport.id).limit(limit))).all())

    async def missing_embeddings(self, model_id: str, limit: int) -> list[MarketReport]:
        stmt = select(MarketReport).where(
            (MarketReport.embedding.is_(None)) | (MarketReport.embedding_model != model_id)).limit(limit)
        return list((await self.session.scalars(stmt)).all())

    async def semantic(self, vec: list[float], model_id: str, k: int, *, crop: str | None = None,
                       location: str | None = None) -> list[tuple[MarketReport, float]]:
        dist = MarketReport.embedding.cosine_distance(vec).label("dist")
        stmt = select(MarketReport, dist).where(MarketReport.embedding.is_not(None), MarketReport.embedding_model == model_id)
        if crop:
            stmt = stmt.where(func.lower(MarketReport.crop) == crop.lower())
        if location:
            stmt = stmt.where(MarketReport.location.ilike(f"%{location}%"))
        stmt = stmt.order_by(dist).limit(k)
        return [(r, 1.0 - float(d)) for r, d in (await self.session.execute(stmt)).all()]

    async def keyword(self, *, crop: str | None, location: str | None, k: int) -> list[MarketReport]:
        stmt = select(MarketReport)
        if crop:
            stmt = stmt.where(func.lower(MarketReport.crop) == crop.lower())
        if location:
            stmt = stmt.where(MarketReport.location.ilike(f"%{location}%"))
        return list((await self.session.scalars(stmt.order_by(MarketReport.report_date.desc()).limit(k))).all())

    async def get(self, report_id: uuid.UUID) -> MarketReport | None:
        return await self.session.get(MarketReport, report_id)
