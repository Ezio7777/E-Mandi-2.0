import uuid
from datetime import datetime

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import DocumentStatus
from app.models.listing_document import ListingDocument as D


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, doc_id: uuid.UUID, *, for_update: bool = False) -> D | None:
        stmt = select(D).where(D.id == doc_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return await self.session.scalar(stmt)

    async def get_by_key(self, key: str) -> D | None:
        return await self.session.scalar(select(D).where(D.s3_key == key))

    async def count_for_listing(self, listing_id: uuid.UUID) -> int:
        return await self.session.scalar(select(func.count()).select_from(D).where(D.listing_id == listing_id)) or 0

    async def list_for_listing(self, listing_id: uuid.UUID, *, only_verified: bool) -> list[D]:
        stmt = select(D).where(D.listing_id == listing_id)
        if only_verified:
            stmt = stmt.where(D.status == DocumentStatus.VERIFIED)
        return list((await self.session.scalars(stmt.order_by(D.created_at, D.id))).all())

    async def list_by_status(self, status: DocumentStatus, cursor: tuple[datetime, uuid.UUID] | None, limit: int) -> list[D]:
        stmt = select(D).where(D.status == status)
        if cursor:
            stmt = stmt.where(tuple_(D.created_at, D.id) < tuple_(cursor[0], cursor[1]))
        return list((await self.session.scalars(stmt.order_by(D.created_at.desc(), D.id.desc()).limit(limit + 1))).all())

    async def add(self, doc: D) -> D:
        self.session.add(doc)
        await self.session.flush()
        return doc

    async def delete(self, doc: D) -> None:
        await self.session.delete(doc)
        await self.session.flush()
