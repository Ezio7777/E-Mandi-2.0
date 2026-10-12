import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.listing_image import ListingImage


class ImageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, image_id: uuid.UUID) -> ListingImage | None:
        return await self.session.get(ListingImage, image_id)

    async def get_by_key(self, key: str) -> ListingImage | None:
        return await self.session.scalar(select(ListingImage).where(ListingImage.s3_key == key))

    async def list_for_listing(self, listing_id: uuid.UUID) -> list[ListingImage]:
        return list((await self.session.scalars(
            select(ListingImage).where(ListingImage.listing_id == listing_id).order_by(ListingImage.created_at))).all())

    async def count_for_listing(self, listing_id: uuid.UUID) -> int:
        return await self.session.scalar(
            select(func.count()).select_from(ListingImage).where(ListingImage.listing_id == listing_id)) or 0

    async def add(self, image: ListingImage) -> ListingImage:
        self.session.add(image)
        await self.session.flush()
        return image

    async def delete(self, image: ListingImage) -> None:
        await self.session.delete(image)
        await self.session.flush()
