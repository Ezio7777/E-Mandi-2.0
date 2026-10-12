"""Frontend-contract aliases for uploads: POST /uploads/init -> {uploadUrl, fields, objectKey}; POST /uploads/confirm.
Thin adapters over the Stage 6 ImageService (same validation/security); /images/* remains the canonical internal API."""
from fastapi import APIRouter, Depends

from app.api.routes.images import ImageServiceDep
from app.core.dependencies import CurrentUser, RequestContextDep
from app.core.rate_limit import rate_limit
from app.schemas.common import Envelope
from app.schemas.image import UploadConfirmIn, UploadedImageOut, UploadInitIn, UploadInitOut, UploadInitRequest

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("/init", response_model=Envelope[UploadInitOut],
             dependencies=[Depends(rate_limit("image_init", 30, 60, per_user=True))])
async def uploads_init(body: UploadInitIn, user: CurrentUser, svc: ImageServiceDep):
    r = await svc.init_listing_upload(user, UploadInitRequest(
        listing_id=body.listing_id, filename=body.filename, content_type=body.content_type,
        size_bytes=body.size_bytes, replace_image_id=body.replace_image_id))
    return Envelope(data=UploadInitOut(upload_url=r.url, fields=r.fields, object_key=r.object_key,
                                       upload_token=r.upload_token, expires_in=r.expires_in, max_bytes=r.max_bytes))


@router.post("/confirm", response_model=Envelope[UploadedImageOut])
async def uploads_confirm(body: UploadConfirmIn, user: CurrentUser, svc: ImageServiceDep, ctx: RequestContextDep):
    res = await svc.confirm_listing_upload(user, body.upload_token, ctx)
    return Envelope(data=UploadedImageOut(**(await svc.to_out(res.image)).model_dump()))
