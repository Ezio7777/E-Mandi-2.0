"""Buyer Matching Agent (LangGraph).

  validate_requirement -> filter_inventory -> search_step --(enough stock? / steps left?)--> rank -> persist
                                                  ^                 |
                                                  +-- expand_scope <-+   (radius widens: 0 -> 50 -> 150 -> 400 -> anywhere)

The agent controls the multi-step SEARCH WORKFLOW. Eligibility and scoring come exclusively from the deterministic
engine (services/matching.py); no LLM chooses or scores inventory. Each run records a step-by-step trace.
"""
import uuid
from decimal import Decimal
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import transactional
from app.models.buyer_requirement import BuyerRequirement
from app.models.enums import ListingStatus as L
from app.models.enums import MatchStatus, NotificationType, RequirementStatus
from app.models.listing import Listing
from app.models.match import Match
from app.repositories.listing import grades_at_least
from app.repositories.requirement import RequirementRepository
from app.services.audit import SYSTEM_ACTOR, AuditService
from app.services.matching import (
    Candidate, Requirement, Scored, in_scope, is_eligible, locate, rank, score_candidate, total_available,
)
from app.services.notification import NotificationService
from app.utils.crops import crop_or_title
from app.utils.geo import resolve_point
from app.utils.money import fmt_kg, paise_to_rupees

POOL_LIMIT = 500


class MatchState(TypedDict, total=False):
    requirement_id: uuid.UUID
    execution_id: uuid.UUID | None
    buyer_id: uuid.UUID
    req: Requirement
    steps: list[int]
    step_idx: int
    pool: list[Candidate]
    found: dict[Any, Scored]
    trace: list[dict[str, Any]]
    selected: list[Scored]
    outcome: str  # matched | partial | no_match | skipped
    tool_calls: list[dict[str, Any]]


def _after_search(state: MatchState) -> str:
    if total_available(list(state["found"].values())) >= state["req"].quantity_kg:
        return "rank"  # requirement sufficiently satisfied: stop expanding
    return "expand" if state["step_idx"] + 1 < len(state["steps"]) else "rank"  # search limit reached


class BuyerMatchingAgent:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session, self.settings = session, settings
        self.requirements = RequirementRepository(session)
        self.graph = self._build()

    def _build(self):  # noqa: ANN202
        g = StateGraph(MatchState)
        for n in ("validate_requirement", "filter_inventory", "search_step", "expand_scope", "rank", "persist"):
            g.add_node(n, getattr(self, n))
        g.add_edge(START, "validate_requirement")
        g.add_conditional_edges("validate_requirement", lambda s: "stop" if s.get("outcome") == "skipped" else "next",
                                {"next": "filter_inventory", "stop": END})
        g.add_edge("filter_inventory", "search_step")
        g.add_conditional_edges("search_step", _after_search, {"expand": "expand_scope", "rank": "rank"})
        g.add_edge("expand_scope", "search_step")
        g.add_edge("rank", "persist")
        g.add_edge("persist", END)
        return g.compile()

    async def run(self, requirement_id: uuid.UUID, execution_id: uuid.UUID | None = None) -> MatchState:
        return await self.graph.ainvoke({"requirement_id": requirement_id, "execution_id": execution_id, "tool_calls": []})

    # ---------------- nodes ----------------
    async def validate_requirement(self, s: MatchState) -> dict[str, Any]:
        r = await self.requirements.get(s["requirement_id"])
        steps = self.settings.match_radius_steps
        if r is None or r.status in {RequirementStatus.CANCELLED, RequirementStatus.FULFILLED} or r.quantity_kg <= 0 or not steps:
            return {"outcome": "skipped"}
        req = Requirement(crop=crop_or_title(r.crop_name), quantity_kg=r.quantity_kg, min_grade=r.min_grade,
                          location=r.location, max_price_paise=r.max_price_paise, needed_by=r.needed_by,
                          geo=resolve_point(r.location))
        return {"req": req, "buyer_id": r.buyer_id, "steps": steps, "step_idx": 0, "found": {}, "trace": []}

    async def filter_inventory(self, s: MatchState) -> dict[str, Any]:
        """Deterministic SQL gates: crop, ACTIVE, grade >= min, price <= ceiling, stock > 0, not the buyer's own."""
        req = s["req"]
        rows = (await self.session.scalars(select(Listing).where(
            func.lower(Listing.crop_name) == req.crop.lower(), Listing.status == L.ACTIVE,
            Listing.ai_grade.in_(grades_at_least(req.min_grade)), Listing.base_price_paise <= req.max_price_paise,
            Listing.quantity_kg - Listing.reserved_kg > 0, Listing.farmer_id != s["buyer_id"])
            .order_by(Listing.created_at, Listing.id).limit(POOL_LIMIT))).unique().all()
        dismissed = set((await self.session.scalars(select(Match.listing_id).where(
            Match.requirement_id == s["requirement_id"], Match.status == MatchStatus.DISMISSED))).all())
        pool = [Candidate(l.id, l.farmer_id, l.crop_name, l.available_kg, l.base_price_paise, l.ai_grade, l.location,
                          resolve_point(l.location, l.latitude, l.longitude), l.harvest_date)
                for l in rows if l.id not in dismissed]
        pool = [c for c in pool if is_eligible(req, c)]
        return {"pool": pool, "tool_calls": [*s["tool_calls"], {"tool": "inventory_filter", "ok": True, "n": len(pool)}]}

    async def search_step(self, s: MatchState) -> dict[str, Any]:
        idx, radius, req = s["step_idx"], s["steps"][s["step_idx"]], s["req"]
        found = dict(s["found"])
        new = 0
        for c in s["pool"]:
            if c.listing_id in found:
                continue
            dist, same = locate(req, c)
            if in_scope(dist, same, radius):
                sc = score_candidate(req, c, dist, same)
                sc.search_step = idx
                found[c.listing_id] = sc
                new += 1
        covered = total_available(list(found.values()))
        step = {"tool": "search_step", "ok": True, "step": idx, "radius_km": radius, "new": new,
                "candidates": len(found), "covered_kg": str(covered), "satisfied": covered >= req.quantity_kg}
        return {"found": found, "trace": [*s["trace"], step], "tool_calls": [*s["tool_calls"], step]}

    async def expand_scope(self, s: MatchState) -> dict[str, Any]:
        return {"step_idx": s["step_idx"] + 1}

    async def rank(self, s: MatchState) -> dict[str, Any]:
        selected = rank(list(s["found"].values()))[: self.settings.MATCH_MAX_RESULTS]
        if not selected:
            outcome = "no_match"
        else:
            outcome = "matched" if total_available(selected) >= s["req"].quantity_kg else "partial"
        return {"selected": selected, "outcome": outcome}

    async def persist(self, s: MatchState) -> dict[str, Any]:
        sel, req, rid = s["selected"], s["req"], s["requirement_id"]
        notif = NotificationService(self.session)
        async with transactional(self.session):
            r = await self.requirements.get_for_update(rid)
            if r is None or r.status in {RequirementStatus.CANCELLED, RequirementStatus.FULFILLED}:
                return {"outcome": "skipped"}
            before = set((await self.session.scalars(select(Match.listing_id).where(Match.requirement_id == rid))).all())
            if sel:
                rows = [dict(requirement_id=rid, listing_id=m.listing_id, score=m.score, grade_score=m.grade_score,
                             quantity_score=m.quantity_score, location_score=m.location_score, price_score=m.price_score,
                             availability_score=m.availability_score, reasons=m.reasons, breakdown=m.breakdown,
                             distance_km=m.distance_km, search_step=m.search_step, rank=i + 1,
                             execution_id=s.get("execution_id"), status=MatchStatus.SUGGESTED) for i, m in enumerate(sel)]
                stmt = pg_insert(Match).values(rows)
                await self.session.execute(stmt.on_conflict_do_update(
                    constraint="uq_matches_pair",  # keeps status (ACCEPTED/DISMISSED) and created_at
                    set_={k: getattr(stmt.excluded, k) for k in (
                        "score", "grade_score", "quantity_score", "location_score", "price_score", "availability_score",
                        "reasons", "breakdown", "distance_km", "search_step", "rank", "execution_id")}))
            await self.session.execute(delete(Match).where(  # drop stale suggestions; never touch decided ones
                Match.requirement_id == rid, Match.status == MatchStatus.SUGGESTED,
                Match.listing_id.not_in([m.listing_id for m in sel]) if sel else True))
            covered = total_available(sel)
            if sel:
                r.status = RequirementStatus.MATCHED
            AuditService(self.session).record(
                action="match.generated", entity_type="buyer_requirement", entity_id=rid, actor=SYSTEM_ACTOR,
                metadata={"outcome": s["outcome"], "matches": len(sel), "covered_kg": str(covered),
                          "steps": s["trace"], "weights_version": "v1",
                          "top": [{"listing_id": str(m.listing_id), "score": m.score} for m in sel[:3]]},
                new_state={"status": r.status.value})
            if sel:
                best = sel[0]
                tail = "" if s["outcome"] == "matched" else f" (covering {fmt_kg(covered)} of {fmt_kg(req.quantity_kg)} kg)"
                notif.add(s["buyer_id"], NotificationType.NEW_MATCH, "New matches found",
                          f"{len(sel)} listing(s) match your {req.crop} requirement{tail}. Best: Rs "
                          f"{paise_to_rupees(best.price_paise)}/kg, score {round(best.score * 100)}.",
                          {"requirement_id": str(rid), "matches": len(sel), "outcome": s["outcome"]})
                notified: set[Any] = set()
                for m in sel:  # farmers learn only that demand exists (no buyer identity), once per new pair
                    if m.listing_id not in before and m.farmer_id not in notified:
                        notified.add(m.farmer_id)
                        notif.add(m.farmer_id, NotificationType.NEW_MATCH, f"A buyer wants {req.crop}",
                                  f"A buyer needs {fmt_kg(req.quantity_kg)} kg of {req.crop} (Grade {req.min_grade.value}+) "
                                  f"near {req.location}. Your listing is a match.",
                                  {"listing_id": str(m.listing_id), "requirement_id": str(rid)})
            else:
                notif.add(s["buyer_id"], NotificationType.SYSTEM, "No matches yet",
                          f"No active listings currently meet your {req.crop} requirement. Try raising your price limit "
                          "or lowering the minimum grade.", {"requirement_id": str(rid), "kind": "matching"})
        return {}
