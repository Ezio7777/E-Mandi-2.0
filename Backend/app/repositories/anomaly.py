import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.anomaly_event import AnomalyEvent
from app.models.enums import AnomalySeverity, AnomalyStatus


class AnomalyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def insert_if_new(self, values: dict[str, Any]) -> uuid.UUID | None:
        """Idempotent on dedupe_key: re-running the agent for the same event never duplicates a flag. Returns the id only
        for a NEW row (so admins are notified once)."""
        res = await self.session.execute(pg_insert(AnomalyEvent).values(id=uuid.uuid4(), **values)
                                         .on_conflict_do_nothing(index_elements=["dedupe_key"]).returning(AnomalyEvent.id))
        return res.scalar_one_or_none()

    async def get(self, anomaly_id: uuid.UUID, *, for_update: bool = False) -> AnomalyEvent | None:
        stmt = select(AnomalyEvent).where(AnomalyEvent.id == anomaly_id).execution_options(populate_existing=True)
        return await self.session.scalar(stmt.with_for_update() if for_update else stmt)

    async def search(self, status: AnomalyStatus | None, severity: AnomalySeverity | None, entity_type: str | None,
                     cursor: tuple[datetime, uuid.UUID] | None, limit: int) -> list[AnomalyEvent]:
        stmt = select(AnomalyEvent)
        if status:
            stmt = stmt.where(AnomalyEvent.status == status)
        if severity:
            stmt = stmt.where(AnomalyEvent.severity == severity)
        if entity_type:
            stmt = stmt.where(AnomalyEvent.entity_type == entity_type)
        if cursor:
            stmt = stmt.where(tuple_(AnomalyEvent.detected_at, AnomalyEvent.id) < tuple_(cursor[0], cursor[1]))
        return list((await self.session.scalars(stmt.order_by(AnomalyEvent.detected_at.desc(), AnomalyEvent.id.desc())
                                                .limit(limit + 1))).all())

    async def open_count(self) -> int:
        return await self.session.scalar(select(func.count()).select_from(AnomalyEvent).where(
            AnomalyEvent.status.in_([AnomalyStatus.FLAGGED_FOR_REVIEW, AnomalyStatus.ACTION_REQUESTED]))) or 0
