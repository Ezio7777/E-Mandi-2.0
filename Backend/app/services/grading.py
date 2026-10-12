"""AI crop grading orchestration.

Gemini is attempted first; OpenAI is used only if Gemini times out / errors / returns invalid output.
Raw model output is never trusted: it must pass strict Pydantic validation AND a deterministic consistency check.
Low confidence or inconsistent results never auto-publish: the listing goes to REVIEW_REQUIRED for an admin.
"""
import time
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import transactional
from app.core.errors import AppError, ConflictError, DomainValidationError, NotFoundError
from app.core.logging import get_logger
from app.integrations.aws.s3 import ObjectStorage
from app.integrations.gemini.vision import GeminiVisionGrader
from app.integrations.openai.vision import OpenAIVisionGrader
from app.integrations.vision_common import GradingProviderError, VisionGrader
from app.models.crop_grading_result import CropGradingResult
from app.models.enums import Grade, GradingProvider, NotificationType, ReviewDecision, UserRole
from app.models.enums import ListingStatus as L
from app.models.grading_review import GradingReview
from app.models.listing import Listing
from app.models.user import User
from app.repositories.image import ImageRepository
from app.repositories.listing import ListingRepository
from app.schemas.grading import GradingOutput, GradingResultOut, ReviewQueueItem, ReviewRequest
from app.services.access import assert_owner_listing
from app.services.audit import SYSTEM_ACTOR, Actor, AuditService, RequestContext
from app.services.notification import NotificationService
from app.services.transitions import LISTING_TRANSITIONS, assert_transition
from app.utils.time import utcnow

log = get_logger(__name__)
_ORDER = [Grade.A, Grade.B, Grade.C, Grade.D]


class GradingUnavailable(AppError):
    status_code, code, message = 503, "grading_unavailable", "AI grading is temporarily unavailable"


def expected_grade(defect_pct: float) -> Grade:
    return Grade.A if defect_pct <= 5 else Grade.B if defect_pct <= 15 else Grade.C if defect_pct <= 30 else Grade.D


def consistency_flags(out: GradingOutput) -> list[str]:
    """Deterministic sanity check between the model's grade and its own defect estimate."""
    if abs(_ORDER.index(out.grade) - _ORDER.index(expected_grade(out.defect_percentage))) > 1:
        return ["grade_inconsistent_with_defect_percentage"]
    return []


def build_graders(settings: Settings) -> list[VisionGrader]:
    return [GeminiVisionGrader(settings), OpenAIVisionGrader(settings)]  # order = priority


class GradingService:
    def __init__(self, session: AsyncSession, settings: Settings, storage: ObjectStorage,
                 graders: list[VisionGrader]) -> None:
        self.session, self.settings, self.storage, self.graders = session, settings, storage, graders
        self.listings, self.images = ListingRepository(session), ImageRepository(session)
        self.audit, self.notify = AuditService(session), NotificationService(session)

    # ---------- provider orchestration ----------
    async def analyze(self, image: bytes, content_type: str, crop_name: str) -> tuple[GradingOutput, int]:
        failed_before = False
        for g in self.graders:
            if not g.available:
                log.info("grader_not_configured", provider=g.name)
                continue
            t0 = time.monotonic()
            try:
                raw = await g.grade(image, content_type, crop_name)
            except GradingProviderError as exc:
                log.warning("grader_failed", provider=exc.provider, kind=exc.kind)
                failed_before = True
                continue
            ms = int((time.monotonic() - t0) * 1000)
            log.info("grader_succeeded", provider=g.name, fallback_used=failed_before, latency_ms=ms)
            return GradingOutput(**raw.model_dump(), provider=g.name, fallback_used=failed_before), ms  # type: ignore[arg-type]
        raise GradingUnavailable()

    async def _cached(self, sha256: str, crop_name: str) -> CropGradingResult | None:
        cutoff = utcnow() - timedelta(days=self.settings.GRADING_CACHE_TTL_DAYS)
        from sqlalchemy import func
        return await self.session.scalar(
            select(CropGradingResult).join(Listing, Listing.id == CropGradingResult.listing_id)
            .where(CropGradingResult.image_sha256 == sha256, func.lower(Listing.crop_name) == crop_name.lower(),
                   CropGradingResult.from_cache.is_(False),
                   CropGradingResult.provider.in_([GradingProvider.GEMINI, GradingProvider.OPENAI]),
                   CropGradingResult.created_at >= cutoff)
            .order_by(CropGradingResult.created_at.desc()).limit(1))

    # ---------- worker entrypoint ----------
    async def grade_listing(self, listing_id: uuid.UUID, *, final_attempt: bool = False) -> CropGradingResult | None:
        """Idempotent: no-op unless the listing is ANALYZING. Raises GradingUnavailable to trigger a job retry
        (unless final_attempt, in which case the listing is routed to manual review instead)."""
        l = await self.listings.get(listing_id)
        if l is None or l.status != L.ANALYZING:
            return None
        image = next((i for i in l.images if i.is_primary), l.images[0] if l.images else None)
        if image is None:
            await self._mark_failed(listing_id, "no_image")
            return None
        cached = await self._cached(image.sha256, l.crop_name)
        if cached is not None:
            out = GradingOutput(grade=cached.grade, confidence=cached.confidence, defect_percentage=cached.defect_percentage,
                                reason=cached.reason, issues=list(cached.issues), provider=cached.provider.value,  # type: ignore[arg-type]
                                fallback_used=cached.fallback_used)
            latency, from_cache = 0, True
        else:
            data = await self.storage.get_bytes(image.s3_key, self.settings.IMAGE_MAX_BYTES)
            try:
                out, latency = await self.analyze(data, image.content_type, l.crop_name)
            except GradingUnavailable:
                if final_attempt:
                    await self._mark_failed(listing_id, "ai_unavailable")
                    return None
                raise
            from_cache = False
        return await self._persist(listing_id, image.id, image.sha256, out, latency, from_cache)

    async def _persist(self, listing_id: uuid.UUID, image_id: uuid.UUID, sha: str, out: GradingOutput,
                       latency: int, from_cache: bool) -> CropGradingResult | None:
        flags = consistency_flags(out)
        needs_review = out.confidence < self.settings.GRADING_CONFIDENCE_THRESHOLD or bool(flags)
        async with transactional(self.session):
            l = await self.listings.get_for_update(listing_id)
            if l is None or l.status != L.ANALYZING:  # state moved while we were calling the provider
                return None
            res = CropGradingResult(
                listing_id=l.id, image_id=image_id, image_sha256=sha, grade=out.grade, confidence=out.confidence,
                defect_percentage=out.defect_percentage, reason=out.reason, issues=out.issues,
                provider=GradingProvider(out.provider), fallback_used=out.fallback_used, from_cache=from_cache,
                latency_ms=latency, requires_review=needs_review)
            self.session.add(res)
            target = L.REVIEW_REQUIRED if needs_review else L.ACTIVE
            assert_transition(LISTING_TRANSITIONS, l.status, target)
            l.status, l.ai_grade, l.grade_confidence = target, out.grade, out.confidence
            await self.session.flush()
            meta = {"provider": out.provider, "fallback_used": out.fallback_used, "from_cache": from_cache,
                    "confidence": out.confidence, "flags": flags}
            self.audit.record(action="grading.completed", entity_type="listing", entity_id=l.id, actor=SYSTEM_ACTOR,
                              metadata=meta, previous_state={"status": "ANALYZING"},
                              new_state={"status": target.value, "grade": out.grade.value})
            if needs_review:
                self.audit.record(action="grading.review_required", entity_type="listing", entity_id=l.id,
                                  actor=SYSTEM_ACTOR, metadata={"threshold": self.settings.GRADING_CONFIDENCE_THRESHOLD, **meta})
                self.notify.add(l.farmer_id, NotificationType.REVIEW_REQUIRED, "Listing under review",
                                f"Your {l.crop_name} listing needs a quick manual quality check before it goes live.",
                                {"listing_id": str(l.id)})
                await self.notify.notify_admins(NotificationType.REVIEW_REQUIRED, "Grading review required",
                                                f"{l.crop_name}: AI confidence {out.confidence:.2f}",
                                                {"listing_id": str(l.id)})
            else:
                self.notify.add(l.farmer_id, NotificationType.GRADING_COMPLETED, "Grading complete",
                                f"Your {l.crop_name} was graded {out.grade.value} and is now live.",
                                {"listing_id": str(l.id), "grade": out.grade.value})
        return res

    async def _mark_failed(self, listing_id: uuid.UUID, reason: str) -> None:
        async with transactional(self.session):
            l = await self.listings.get_for_update(listing_id)
            if l is None or l.status != L.ANALYZING:
                return
            l.status = L.REVIEW_REQUIRED
            self.audit.record(action="grading.failed", entity_type="listing", entity_id=l.id, actor=SYSTEM_ACTOR,
                              metadata={"reason": reason}, previous_state={"status": "ANALYZING"},
                              new_state={"status": "REVIEW_REQUIRED"})
            self.notify.add(l.farmer_id, NotificationType.REVIEW_REQUIRED, "Listing under review",
                            f"Automatic grading was unavailable; an admin will review your {l.crop_name} listing.",
                            {"listing_id": str(l.id)})
            await self.notify.notify_admins(NotificationType.REVIEW_REQUIRED, "Manual grading needed",
                                            f"{l.crop_name}: automatic grading failed ({reason})", {"listing_id": str(l.id)})

    # ---------- reads ----------
    async def latest_result(self, listing_id: uuid.UUID) -> CropGradingResult | None:
        return await self.session.scalar(select(CropGradingResult).where(CropGradingResult.listing_id == listing_id)
                                         .order_by(CropGradingResult.created_at.desc()).limit(1))

    async def result_for(self, user: User, listing_id: uuid.UUID) -> CropGradingResult:
        l = await self.listings.get(listing_id)
        assert_owner_listing(user, l, allow_admin=True)
        res = await self.latest_result(listing_id)
        if res is None:
            raise NotFoundError("No grading result yet")
        return res

    async def review_queue(self) -> list[ReviewQueueItem]:
        rows = (await self.session.scalars(select(Listing).where(Listing.status == L.REVIEW_REQUIRED)
                                           .order_by(Listing.updated_at))).unique().all()
        items = []
        for l in rows:
            r = await self.latest_result(l.id)
            flags = [] if r is None else (["low_confidence"] if r.confidence < self.settings.GRADING_CONFIDENCE_THRESHOLD else []) + \
                consistency_flags(GradingOutput(grade=r.grade, confidence=r.confidence, defect_percentage=r.defect_percentage,
                                                reason=r.reason, issues=list(r.issues), provider="gemini"))
            items.append(ReviewQueueItem(listing_id=l.id, crop_name=l.crop_name, farmer_id=l.farmer_id,
                                         ai_result=GradingResultOut.model_validate(r) if r else None,
                                         flags=flags or (["ai_unavailable"] if r is None else []), submitted_at=l.updated_at))
        return items

    # ---------- admin decision (human-in-the-loop) ----------
    async def review_listing(self, admin: User, listing_id: uuid.UUID, req: ReviewRequest, ctx: RequestContext) -> Listing:
        if admin.role != UserRole.ADMIN:
            raise NotFoundError()
        if req.decision == ReviewDecision.OVERRIDDEN and req.final_grade is None:
            raise DomainValidationError("final_grade is required when overriding",
                                        details=[{"field": "final_grade", "message": "required"}])
        if req.decision != ReviewDecision.OVERRIDDEN and req.final_grade is not None:
            raise DomainValidationError("final_grade is only allowed when overriding",
                                        details=[{"field": "final_grade", "message": "not allowed"}])
        async with transactional(self.session):
            l = await self.listings.get_for_update(listing_id)
            if l is None:
                raise NotFoundError("Listing not found")
            if l.status != L.REVIEW_REQUIRED:
                raise ConflictError(f"Listing is {l.status.value}; only REVIEW_REQUIRED listings can be reviewed")
            ai = await self.latest_result(l.id)
            if ai is None and req.decision == ReviewDecision.APPROVED:
                raise ConflictError("There is no AI result to approve; override with a grade or reject")
            original = ({"grade": ai.grade.value, "confidence": ai.confidence, "defect_percentage": ai.defect_percentage,
                         "reason": ai.reason, "issues": ai.issues, "provider": ai.provider.value}
                        if ai else {"status": "ai_unavailable"})
            if req.decision == ReviewDecision.OVERRIDDEN:
                grade = req.final_grade
                ai = CropGradingResult(  # manual result row keeps the audit trail uniform
                    listing_id=l.id, image_sha256=next((i.sha256 for i in l.images), "manual"), grade=grade,
                    confidence=1.0, defect_percentage=0.0, reason=f"Admin override: {req.reason}"[:500], issues=[],
                    provider=GradingProvider.MANUAL, requires_review=False)
                self.session.add(ai)
                await self.session.flush()
            elif req.decision == ReviewDecision.APPROVED:
                grade = ai.grade  # type: ignore[union-attr]
            else:
                grade = None
            target = L.ARCHIVED if req.decision == ReviewDecision.REJECTED else L.ACTIVE
            prev = l.status
            assert_transition(LISTING_TRANSITIONS, l.status, target)
            l.status = target
            if grade is not None:
                l.ai_grade = grade
                l.grade_confidence = 1.0 if req.decision == ReviewDecision.OVERRIDDEN else l.grade_confidence
            self.session.add(GradingReview(
                grading_result_id=ai.id, listing_id=l.id, original_result=original, decision=req.decision,  # type: ignore[union-attr]
                final_grade=grade, admin_id=admin.id, reason=req.reason))
            action = {"APPROVED": "grading.review_approved", "OVERRIDDEN": "grading.overridden",
                      "REJECTED": "grading.review_rejected"}[req.decision.value]
            self.audit.record(action=action, entity_type="listing", entity_id=l.id, actor=Actor(admin.id, admin.role),
                              ip=ctx.ip, metadata={"reason": req.reason}, previous_state={"status": prev.value, "ai": original},
                              new_state={"status": target.value, "grade": grade.value if grade else None})
            self.notify.add(l.farmer_id, NotificationType.GRADING_COMPLETED,
                            "Listing approved" if target == L.ACTIVE else "Listing not approved",
                            f"Your {l.crop_name} listing was {'approved' if target == L.ACTIVE else 'rejected'} after review.",
                            {"listing_id": str(l.id), "decision": req.decision.value})
        await self.session.refresh(l)
        await self.session.refresh(l, ["images"])
        return l
