import uuid
from datetime import datetime

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PendingActionStatus, PendingActionType
from app.models.pending_action import PendingAction


class PendingActionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, action_id: uuid.UUID, *, for_update: bool = False) -> PendingAction | None:
        stmt = select(PendingAction).where(PendingAction.id == action_id).execution_options(populate_existing=True)
        return await self.session.scalar(stmt.with_for_update() if for_update else stmt)

    async def open_for(self, action_type: PendingActionType, entity_type: str, entity_id: str) -> PendingAction | None:
        return await self.session.scalar(select(PendingAction).where(
            PendingAction.action_type == action_type, PendingAction.entity_type == entity_type,
            PendingAction.entity_id == entity_id, PendingAction.status == PendingActionStatus.PENDING).limit(1))

    async def search(self, status: PendingActionStatus | None, action_type: PendingActionType | None,
                     cursor: tuple[datetime, uuid.UUID] | None, limit: int) -> list[PendingAction]:
        stmt = select(PendingAction)
        if status:
            stmt = stmt.where(PendingAction.status == status)
        if action_type:
            stmt = stmt.where(PendingAction.action_type == action_type)
        if cursor:
            stmt = stmt.where(tuple_(PendingAction.created_at, PendingAction.id) < tuple_(cursor[0], cursor[1]))
        return list((await self.session.scalars(stmt.order_by(PendingAction.created_at.desc(), PendingAction.id.desc())
                                                .limit(limit + 1))).all())

    async def pending_count(self) -> int:
        return await self.session.scalar(select(func.count()).select_from(PendingAction).where(
            PendingAction.status == PendingActionStatus.PENDING)) or 0
