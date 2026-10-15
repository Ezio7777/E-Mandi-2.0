import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.dependencies import (
    CurrentUser,
    RequestContextDep,
    SessionDep,
    SettingsDep,
    get_storage,
    get_url_resolver,
)
from app.core.rate_limit import rate_limit
from app.integrations.aws.image_url_resolver import ImageUrlResolver
from app.integrations.aws.s3 import ObjectStorage
from app.schemas.common import Envelope
from app.schemas.image import (
    AvatarOut,
    ImageOut,
    ProfileUploadInitRequest,
    UploadConfirmRequest,
    UploadInitRequest,
    UploadInitResponse,
)
from app.services.image import ImageService

router = APIRouter(prefix="/images", tags=["images"])


def get_image_service(session: SessionDep, settings: SettingsDep,
                      storage: Annotated[ObjectStorage, Depends(get_storage)],
                      resolver: Annotated[ImageUrlResolver, Depends(get_url_resolver)]) -> ImageService:
    return ImageService(session, settings, storage, resolver)


ImageServiceDep = Annotated[ImageService, Depends(get_image_service)]
_init_limit = Depends(rate_limit("image_init", 30, 60, per_user=True))


@router.post("/init", response_model=Envelope[UploadInitResponse], dependencies=[_init_limit])
async def init_upload(body: UploadInitRequest, user: CurrentUser, svc: ImageServiceDep):
    return Envelope(data=await svc.init_listing_upload(user, body))


@router.post("/confirm", response_model=Envelope[ImageOut])
async def confirm_upload(body: UploadConfirmRequest, user: CurrentUser, svc: ImageServiceDep, ctx: RequestContextDep):
    res = await svc.confirm_listing_upload(user, body.upload_token, ctx)
    return Envelope(data=await svc.to_out(res.image))


@router.get("/listing/{listing_id}", response_model=Envelope[list[ImageOut]])
async def list_images(listing_id: uuid.UUID, user: CurrentUser, svc: ImageServiceDep):
    return Envelope(data=await svc.list_for_listing(user, listing_id))


@router.post("/{image_id}/primary", response_model=Envelope[ImageOut])
async def set_primary(image_id: uuid.UUID, user: CurrentUser, svc: ImageServiceDep, ctx: RequestContextDep):
    return Envelope(data=await svc.to_out(await svc.set_primary(user, image_id, ctx)))


@router.delete("/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_image(image_id: uuid.UUID, user: CurrentUser, svc: ImageServiceDep, ctx: RequestContextDep) -> None:
    await svc.delete_image(user, image_id, ctx)


@router.post("/profile/init", response_model=Envelope[UploadInitResponse], dependencies=[_init_limit])
async def init_profile_upload(body: ProfileUploadInitRequest, user: CurrentUser, svc: ImageServiceDep):
    return Envelope(data=await svc.init_profile_upload(user, body))


@router.post("/profile/confirm", response_model=Envelope[AvatarOut])
async def confirm_profile_upload(body: UploadConfirmRequest, user: CurrentUser, svc: ImageServiceDep,
                                 ctx: RequestContextDep):
    return Envelope(data=await svc.confirm_profile_upload(user, body.upload_token, ctx))
