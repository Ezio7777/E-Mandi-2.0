from fastapi import APIRouter

from app.core.dependencies import CurrentUser, RequestContextDep, SessionDep
from app.schemas.common import Envelope
from app.schemas.user import ProfileUpdate, UserOut
from app.services.user import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=Envelope[UserOut])
async def me(user: CurrentUser):
    return Envelope(data=UserOut.model_validate(user))


@router.patch("/me/profile", response_model=Envelope[UserOut])
async def update_profile(body: ProfileUpdate, user: CurrentUser, session: SessionDep, ctx: RequestContextDep):
    updated = await UserService(session).update_profile(user, body, ctx)
    return Envelope(data=UserOut.model_validate(updated))
