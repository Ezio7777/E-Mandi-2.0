from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import transactional
from app.models.user import User
from app.models.user_profile import UserProfile
from app.schemas.user import ProfileUpdate
from app.services.audit import Actor, AuditService, RequestContext


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    async def update_profile(self, user: User, data: ProfileUpdate, ctx: RequestContext) -> User:
        changes = data.model_dump(exclude_unset=True)
        async with transactional(self.session):
            if user.profile is None:
                user.profile = UserProfile(display_name=user.full_name)
            before = {k: getattr(user.profile, k) for k in changes}
            for k, v in changes.items():
                setattr(user.profile, k, v)
            self.audit.record(action="user.profile_updated", entity_type="user", entity_id=user.id,
                              actor=Actor(user.id, user.role), ip=ctx.ip, previous_state=before, new_state=changes)
        return user
