"""Buyer requirements lifecycle. Creating one is the `requirement.created` event that triggers the Buyer Matching Agent."""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runtime import dispatch
from app.core.database import transactional
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.models.buyer_requirement import BuyerRequirement
from app.models.enums import AgentName, MatchStatus, RequirementStatus, UserRole
from app.models.user import User
from app.repositories.match import MatchRepository
from app.repositories.requirement import RequirementRepository
from app.schemas.requirement import RequirementCreate, RequirementOut
from app.services.audit import Actor, AuditService, RequestContext
from app.utils.money import paise_to_rupees, rupees_to_paise
from app.workers.queue import JobQueue

ACTIVE_STATES = {RequirementStatus.OPEN, RequirementStatus.MATCHED}


def to_out(r: BuyerRequirement, job_id: str | None = None) -> RequirementOut:
    return RequirementOut(id=r.id, crop_name=r.crop_name, quantity_kg=r.quantity_kg, min_grade=r.min_grade,
                          location=r.location, max_price=paise_to_rupees(r.max_price_paise), needed_by=r.needed_by,
                          notes=r.notes, status=r.status, created_at=r.created_at, match_job_id=job_id)


class RequirementService:
    def __init__(self, session: AsyncSession, queue: JobQueue | None = None) -> None:
        self.session, self.queue = session, queue
        self.repo, self.matches, self.audit = RequirementRepository(session), MatchRepository(session), AuditService(session)

    def _owned(self, user: User, r: BuyerRequirement | None, *, allow_admin: bool = False) -> BuyerRequirement:
        if r is None or not (r.buyer_id == user.id or (allow_admin and user.role == UserRole.ADMIN)):
            raise NotFoundError("Requirement not found")  # 404 for other people's requirements: no existence leak
        return r

    async def create(self, user: User, data: RequirementCreate, ctx: RequestContext) -> tuple[BuyerRequirement, str]:
        if user.role != UserRole.BUYER:
            raise ForbiddenError("Only buyers can create requirements")
        async with transactional(self.session):
            r = BuyerRequirement(buyer_id=user.id, crop_name=data.crop_name, quantity_kg=data.quantity_kg,
                                 min_grade=data.min_grade, location=data.location, max_price_paise=rupees_to_paise(data.max_price),
                                 needed_by=data.needed_by, notes=data.notes, status=RequirementStatus.OPEN)
            self.session.add(r)
            await self.session.flush()
            self.audit.record(action="requirement.created", entity_type="buyer_requirement", entity_id=r.id,
                              actor=Actor(user.id, user.role), ip=ctx.ip,
                              new_state={"crop": r.crop_name, "quantity_kg": str(r.quantity_kg), "min_grade": r.min_grade.value,
                                         "max_price_paise": r.max_price_paise, "location": r.location})
        job_id = await self._trigger(r, "requirement.created")
        return r, job_id

    async def _trigger(self, r: BuyerRequirement, trigger: str) -> str:
        assert self.queue is not None
        eid = await dispatch(self.session, self.queue, agent=AgentName.BUYER_MATCHING, job_name="match_requirement_job",
                             trigger_type=trigger, entity_type="requirement", entity_id=r.id, job_args=(str(r.id),))
        return str(eid)

    async def get(self, user: User, requirement_id: uuid.UUID) -> BuyerRequirement:
        return self._owned(user, await self.repo.get(requirement_id), allow_admin=True)

    async def rematch(self, user: User, requirement_id: uuid.UUID) -> tuple[BuyerRequirement, str]:
        r = self._owned(user, await self.repo.get(requirement_id))
        if r.status not in ACTIVE_STATES:
            raise ConflictError(f"A {r.status.value} requirement cannot be re-matched")
        return r, await self._trigger(r, "requirement.rematch_requested")

    async def cancel(self, user: User, requirement_id: uuid.UUID, ctx: RequestContext) -> BuyerRequirement:
        async with transactional(self.session):
            r = self._owned(user, await self.repo.get_for_update(requirement_id))
            if r.status not in ACTIVE_STATES:
                raise ConflictError(f"A {r.status.value} requirement cannot be cancelled")
            prev, r.status = r.status, RequirementStatus.CANCELLED
            self.audit.record(action="requirement.cancelled", entity_type="buyer_requirement", entity_id=r.id,
                              actor=Actor(user.id, user.role), ip=ctx.ip, previous_state={"status": prev.value},
                              new_state={"status": "CANCELLED"})
        return r

    async def dismiss_match(self, user: User, match_id: uuid.UUID, ctx: RequestContext) -> None:
        async with transactional(self.session):
            m = await self.matches.get(match_id)
            if m is None:
                raise NotFoundError("Match not found")
            self._owned(user, await self.repo.get(m.requirement_id))
            if m.status == MatchStatus.ACCEPTED:
                raise ConflictError("An accepted match cannot be dismissed")
            m.status = MatchStatus.DISMISSED
            self.audit.record(action="match.dismissed", entity_type="match", entity_id=m.id, actor=Actor(user.id, user.role),
                              ip=ctx.ip, metadata={"requirement_id": str(m.requirement_id), "listing_id": str(m.listing_id)})
