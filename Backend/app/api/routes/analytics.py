from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import RedisDep, SessionDep, SettingsDep, require_roles
from app.core.rate_limit import rate_limit
from app.models.enums import UserRole
from app.schemas.analytics import Metric, OverviewOut, TimeseriesOut, TopCropsOut
from app.schemas.common import Envelope
from app.services.analytics import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"], dependencies=[Depends(require_roles(UserRole.ADMIN)),
                                                                          Depends(rate_limit("analytics", 120, 60, per_user=True))])


def _svc(session: SessionDep, settings: SettingsDep, redis: RedisDep) -> AnalyticsService:
    return AnalyticsService(session, settings, redis)


Svc = Annotated[AnalyticsService, Depends(_svc)]


@router.get("/overview", response_model=Envelope[OverviewOut])
async def overview(svc: Svc, days: Annotated[int, Query(ge=1, le=365)] = 30, refresh: bool = False):
    """Marketplace KPIs for the window. Served from a short Redis cache (meta.cached); ?refresh=true recomputes."""
    out, cached = await svc.overview(days, refresh=refresh)
    return Envelope(data=out, meta={"cached": cached})


@router.get("/timeseries", response_model=Envelope[TimeseriesOut])
async def timeseries(svc: Svc, metric: Metric, days: Annotated[int, Query(ge=1, le=180)] = 30):
    return Envelope(data=await svc.timeseries(metric, days))


@router.get("/top-crops", response_model=Envelope[TopCropsOut])
async def top_crops(svc: Svc, days: Annotated[int, Query(ge=1, le=365)] = 30, limit: Annotated[int, Query(ge=1, le=20)] = 5):
    return Envelope(data=await svc.top_crops(days, limit))
