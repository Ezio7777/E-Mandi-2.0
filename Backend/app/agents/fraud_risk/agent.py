"""Fraud & Risk Agent (LangGraph). Event-driven: runs only when a business event enqueues an assessment.

  load_context -> run_rules --(no signals)--> END
                      \\--(signals)--> summarize (optional AI assist) -> persist -> END

  * run_rules is DETERMINISTIC (agents/fraud_risk/rules.py). Classification is normal | FLAGGED_FOR_REVIEW - the agent never
    labels anything "fraud" and never blocks or changes a user/order/listing itself.
  * summarize is optional and can only add validated text; it cannot alter severity or status.
  * persist is idempotent (dedupe_key), audits, and notifies admins (MEDIUM/HIGH). With RISK_PROPOSE_BAN_ON_HIGH the only
    escalation is a PENDING BAN_USER request that a human admin must approve.
"""
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.fraud_risk import context as C
from app.agents.fraud_risk import rules as R
from app.agents.fraud_risk.events import LISTING_EVENTS
from app.agents.fraud_risk.summarizer import summarize
from app.core.config import Settings
from app.core.database import transactional
from app.core.errors import AppError
from app.core.logging import get_logger
from app.integrations.llm_common import TextLLM
from app.models.enums import AnomalySeverity, AnomalyStatus, NotificationType, PendingActionType
from app.repositories.anomaly import AnomalyRepository
from app.services.audit import SYSTEM_ACTOR, AuditService, RequestContext
from app.services.notification import NotificationService

log = get_logger(__name__)


class RiskState(TypedDict, total=False):
    event_type: str
    entity_type: str
    entity_id: str
    ctx: Any
    signals: list[R.Signal]
    new_events: list[tuple[str, R.Signal]]
    summary: str | None
    summary_provider: str | None
    degraded: bool
    outcome: str  # skipped | normal | flagged
    tool_calls: list[dict[str, Any]]


class FraudRiskAgent:
    def __init__(self, session: AsyncSession, settings: Settings, llms: list[TextLLM] | None = None) -> None:
        self.session, self.settings, self.llms = session, settings, llms or []
        self.graph = self._build()

    def _build(self):
        g = StateGraph(RiskState)
        for n in ("load_context", "run_rules", "summarize", "persist"):
            g.add_node(n, getattr(self, n))
        g.add_edge(START, "load_context")
        g.add_conditional_edges("load_context", lambda s: "stop" if s.get("outcome") == "skipped" else "go", {"go": "run_rules", "stop": END})
        g.add_conditional_edges("run_rules", lambda s: "flag" if s["signals"] else "stop", {"flag": "summarize", "stop": END})
        g.add_edge("summarize", "persist")
        g.add_edge("persist", END)
        return g.compile()

    async def run(self, event_type: str, entity_type: str, entity_id: str) -> RiskState:
        return await self.graph.ainvoke({"event_type": event_type, "entity_type": entity_type, "entity_id": entity_id,
                                         "signals": [], "new_events": [], "tool_calls": [], "degraded": False})

    # ------------------------------------------------------------------ nodes
    async def load_context(self, s: RiskState) -> dict[str, Any]:
        et, kind = s["event_type"], s["entity_type"]
        try:
            eid = uuid.UUID(s["entity_id"])
        except ValueError:
            return {"outcome": "skipped"}
        ctx: Any = None
        if kind == "listing" and et in LISTING_EVENTS:
            ctx = await C.listing_context(self.session, eid)
        elif kind == "order" and et == "order.created":
            ctx = await C.order_context(self.session, eid)
        elif kind == "payment" and et == "payment.failed":
            ctx = await C.payment_context(self.session, eid, self.settings)
        calls = [{"tool": "collect_context", "ok": ctx is not None, "entity": kind}]
        return {"ctx": ctx, "outcome": "normal" if ctx is not None else "skipped", "tool_calls": calls}

    async def run_rules(self, s: RiskState) -> dict[str, Any]:
        ctx, st = s["ctx"], self.settings
        signals = (R.listing_rules(ctx, st) if isinstance(ctx, R.ListingCtx) else R.order_rules(ctx, st) if isinstance(ctx, R.OrderCtx)
                   else R.payment_rules(ctx, st))
        return {"signals": signals, "tool_calls": [*s["tool_calls"], {"tool": "risk_rules", "ok": True, "signals": len(signals)}]}

    async def summarize(self, s: RiskState) -> dict[str, Any]:
        if not any(l.available for l in self.llms):
            return {}
        res = await summarize(self.llms, s["signals"])
        return {"summary": res.text, "summary_provider": res.provider, "degraded": res.failed,
                "tool_calls": [*s["tool_calls"], {"tool": "ai_summary", "ok": res.text is not None}]}

    async def persist(self, s: RiskState) -> dict[str, Any]:
        repo, audit, notify = AnomalyRepository(self.session), AuditService(self.session), NotificationService(self.session)
        new: list[tuple[str, R.Signal]] = []
        async with transactional(self.session):
            for sig in s["signals"]:
                details = {**sig.details, "subject_user_id": str(sig.subject_user_id) if sig.subject_user_id else None}
                if s.get("summary"):
                    details["ai_summary"] = {"text": s["summary"], "provider": s.get("summary_provider")}
                new_id = await repo.insert_if_new(dict(
                    rule_id=sig.rule_id, severity=sig.severity, status=AnomalyStatus.FLAGGED_FOR_REVIEW, entity_type=sig.entity_type,
                    entity_id=sig.entity_id, reason=sig.reason, recommended_action=sig.recommended_action, details=details,
                    dedupe_key=sig.dedupe_key))
                if new_id is None:
                    continue  # already flagged for this exact situation
                new.append((str(new_id), sig))
                audit.record(action="risk.flagged", entity_type="anomaly", entity_id=new_id, actor=SYSTEM_ACTOR,
                             metadata={"rule_id": sig.rule_id, "severity": sig.severity.value, "target": f"{sig.entity_type}:{sig.entity_id}",
                                       "event": s["event_type"]}, new_state={"status": "FLAGGED_FOR_REVIEW"})
                if sig.severity != AnomalySeverity.LOW:  # LOW flags stay in the list without pinging admins
                    await notify.notify_admins(NotificationType.SYSTEM, "Flagged for review",
                                               f"{sig.rule_id.replace('_', ' ').title()} ({sig.severity.value.lower()}): {sig.reason[:160]}",
                                               {"anomaly_id": str(new_id), "entity_type": sig.entity_type, "entity_id": sig.entity_id})
        if self.settings.RISK_PROPOSE_BAN_ON_HIGH:
            await self._propose(new)
        return {"new_events": new, "outcome": "flagged"}

    async def _propose(self, new: list[tuple[str, R.Signal]]) -> None:
        from app.services.approval import ApprovalService
        for anomaly_id, sig in new:
            if sig.severity != AnomalySeverity.HIGH or sig.subject_user_id is None:
                continue
            try:  # a PROPOSAL only: a human admin must approve before anything happens
                await ApprovalService(self.session, self.settings).request(
                    None, PendingActionType.BAN_USER,
                    {"user_id": str(sig.subject_user_id), "reason": f"Proposed after {sig.rule_id} flag; needs admin review"},
                    RequestContext(), via="agent", anomaly_id=uuid.UUID(anomaly_id))
            except AppError as exc:
                log.info("risk_proposal_skipped", code=exc.code)
