import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import CurrentUser, RequestContextDep, SessionDep, SettingsDep, forbid_demo, get_storage, require_roles
from app.core.rate_limit import rate_limit
from app.integrations.aws.s3 import ObjectStorage
from app.models.enums import DocumentStatus, UserRole
from app.schemas.common import Envelope
from app.schemas.document import DocumentConfirmRequest, DocumentInitRequest, DocumentOut, DocumentPage, DocumentRejectRequest
from app.schemas.image import UploadInitResponse
from app.services.document import DocumentService

router = APIRouter(prefix="/documents", tags=["documents"])


def get_document_service(session: SessionDep, settings: SettingsDep, storage: Annotated[ObjectStorage, Depends(get_storage)]) -> DocumentService:
    return DocumentService(session, settings, storage)


Svc = Annotated[DocumentService, Depends(get_document_service)]
_admin = [Depends(require_roles(UserRole.ADMIN)), Depends(rate_limit("admin", 240, 60, per_user=True))]


@router.post("/init", response_model=Envelope[UploadInitResponse], dependencies=[Depends(rate_limit("document_init", 20, 60, per_user=True))])
async def init_upload(body: DocumentInitRequest, user: CurrentUser, svc: Svc):
    return Envelope(data=await svc.init_upload(user, body))


@router.post("/confirm", response_model=Envelope[DocumentOut], status_code=status.HTTP_201_CREATED)
async def confirm_upload(body: DocumentConfirmRequest, user: CurrentUser, svc: Svc, ctx: RequestContextDep):
    doc, _ = await svc.confirm_upload(user, body.upload_token, ctx)
    return Envelope(data=await svc.to_out(doc))


@router.get("/listing/{listing_id}", response_model=Envelope[list[DocumentOut]])
async def list_documents(listing_id: uuid.UUID, user: CurrentUser, svc: Svc):
    return Envelope(data=await svc.list_for_listing(user, listing_id))


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: uuid.UUID, user: CurrentUser, svc: Svc, ctx: RequestContextDep):
    await svc.delete(user, document_id, ctx)


@router.get("/admin/queue", response_model=Envelope[DocumentPage], dependencies=_admin)
async def review_queue(svc: Svc, status_: Annotated[DocumentStatus, Query(alias="status")] = DocumentStatus.PENDING_REVIEW,
                       cursor: str | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 20):
    return Envelope(data=await svc.pending(status_, cursor, limit))


@router.post("/{document_id}/verify", response_model=Envelope[DocumentOut], dependencies=[*_admin, Depends(forbid_demo)])
async def verify(document_id: uuid.UUID, user: CurrentUser, svc: Svc, ctx: RequestContextDep):
    return Envelope(data=await svc.to_out(await svc.review(user, document_id, True, None, ctx)))


@router.post("/{document_id}/reject", response_model=Envelope[DocumentOut], dependencies=[*_admin, Depends(forbid_demo)])
async def reject(document_id: uuid.UUID, body: DocumentRejectRequest, user: CurrentUser, svc: Svc, ctx: RequestContextDep):
    return Envelope(data=await svc.to_out(await svc.review(user, document_id, False, body.reason, ctx)))
