import uuid

from fastapi import APIRouter, Depends

from app.core.dependencies import CurrentUser, RequestContextDep, SessionDep, require_roles
from app.models.enums import UserRole
from app.schemas.common import Envelope
from app.schemas.listing import InventoryAdjust, InventoryItemOut
from app.services.inventory import InventoryService

router = APIRouter(prefix="/inventory", tags=["inventory"], dependencies=[Depends(require_roles(UserRole.FARMER))])


@router.get("", response_model=Envelope[list[InventoryItemOut]])
async def my_inventory(user: CurrentUser, session: SessionDep):
    return Envelope(data=await InventoryService(session).inventory_for(user))


@router.patch("/{listing_id}", response_model=Envelope[InventoryItemOut])
async def adjust(listing_id: uuid.UUID, body: InventoryAdjust, user: CurrentUser, session: SessionDep,
                 ctx: RequestContextDep):
    l = await InventoryService(session).adjust_quantity(user, listing_id, body.quantity_kg, body.reason, ctx)
    return Envelope(data=InventoryItemOut(listing_id=l.id, crop_name=l.crop_name, status=l.status,
                                          quantity_kg=l.quantity_kg, reserved_kg=l.reserved_kg,
                                          available_kg=l.available_kg))
