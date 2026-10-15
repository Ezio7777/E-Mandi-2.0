import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.agents.fraud_risk.events import emit_risk_event
from app.core.dependencies import CurrentUser, RequestContextDep, SessionDep, SettingsDep, forbid_demo, get_job_queue, require_roles
from app.core.errors import NotFoundError
from app.core.rate_limit import rate_limit
from app.models.enums import AnomalySeverity, AnomalyStatus, PendingActionStatus, PendingActionType, UserRole
from app.schemas.admin import (
    ActionRequestIn,
    AnomalyActionIn,
    AnomalyOut,
    AnomalyPage,
    DecisionIn,
    NoteIn,
    PendingActionOut,
    PendingActionPage,
    RiskAssessIn,
    WorkerStatusOut,
)
from app.schemas.common import Envelope
from app.schemas.pricing import JobAccepted
from app.services.anomaly import AnomalyService
from app.services.approval import ApprovalService, out
from app.workers.queue import JobQueue

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_roles(UserRole.ADMIN)),
                                                                   Depends(rate_limit("admin", 240, 60, per_user=True))])


def _anomalies(session: SessionDep, settings: SettingsDep) -> AnomalyService:
    return AnomalyService(session, settings)


def _approvals(session: SessionDep, settings: SettingsDep) -> ApprovalService:
    return ApprovalService(session, settings)


AnomSvc = Annotated[AnomalyService, Depends(_anomalies)]
ApprSvc = Annotated[ApprovalService, Depends(_approvals)]
Cursor = Annotated[str | None, Query(max_length=300)]
Limit = Annotated[int, Query(ge=1, le=50)]


# ------------------------------------------------------------------ risk flags (FLAGGED_FOR_REVIEW)
@router.get("/anomalies", response_model=Envelope[AnomalyPage])
async def list_anomalies(svc: AnomSvc, status: AnomalyStatus | None = None, severity: AnomalySeverity | None = None,
                         entity_type: Annotated[str | None, Query(max_length=50)] = None, cursor: Cursor = None, limit: Limit = 20):
    return Envelope(data=await svc.list_anomalies(status, severity, entity_type, cursor, limit))


@router.get("/anomalies/{anomaly_id}", response_model=Envelope[AnomalyOut])
async def get_anomaly(anomaly_id: uuid.UUID, svc: AnomSvc):
    return Envelope(data=AnomalyOut.model_validate(await svc.get(anomaly_id)))


@router.post("/anomalies/{anomaly_id}/dismiss", response_model=Envelope[AnomalyOut], dependencies=[Depends(forbid_demo)])
async def dismiss(anomaly_id: uuid.UUID, body: NoteIn, admin: CurrentUser, svc: AnomSvc, ctx: RequestContextDep):
    return Envelope(data=AnomalyOut.model_validate(await svc.dismiss(admin, anomaly_id, body.note, ctx)))


@router.post("/anomalies/{anomaly_id}/resolve", response_model=Envelope[AnomalyOut], dependencies=[Depends(forbid_demo)])
async def resolve(anomaly_id: uuid.UUID, body: NoteIn, admin: CurrentUser, svc: AnomSvc, ctx: RequestContextDep):
    return Envelope(data=AnomalyOut.model_validate(await svc.resolve(admin, anomaly_id, body.note, ctx)))


@router.post("/anomalies/{anomaly_id}/request-action", response_model=Envelope[PendingActionOut], status_code=201,
             dependencies=[Depends(forbid_demo)])
async def request_action(anomaly_id: uuid.UUID, body: AnomalyActionIn, admin: CurrentUser, svc: AnomSvc, ctx: RequestContextDep):
    """Escalate a flag into a pending action. Nothing executes until a DIFFERENT admin approves it."""
    return Envelope(data=out(await svc.request_action(admin, anomaly_id, body.action_type, body.payload, ctx)))


@router.post("/risk/assess", response_model=Envelope[JobAccepted], status_code=202,
             dependencies=[Depends(rate_limit("risk_assess", 20, 60, per_user=True))])
async def assess(body: RiskAssessIn, session: SessionDep, queue: Annotated[JobQueue, Depends(get_job_queue)]):
    """Re-run the deterministic risk rules for one entity (idempotent: existing flags are not duplicated)."""
    event = {"listing": "listing.updated", "order": "order.created", "payment": "payment.failed"}[body.entity_type]
    job_id = await emit_risk_event(session, queue, event, body.entity_id)
    if job_id is None:
        raise NotFoundError("Could not queue the assessment")
    return Envelope(data=JobAccepted(job_id=str(job_id)))


# ------------------------------------------------------------------ human approval queue
@router.get("/pending-actions", response_model=Envelope[PendingActionPage])
async def list_pending(svc: ApprSvc, status: PendingActionStatus | None = None, action_type: PendingActionType | None = None,
                       cursor: Cursor = None, limit: Limit = 20):
    return Envelope(data=await svc.list_actions(status, action_type, cursor, limit))


@router.post("/pending-actions", response_model=Envelope[PendingActionOut], status_code=201, dependencies=[Depends(forbid_demo)])
async def create_pending(body: ActionRequestIn, admin: CurrentUser, svc: ApprSvc, ctx: RequestContextDep):
    return Envelope(data=out(await svc.request(admin, body.action_type, body.payload, ctx)))


@router.get("/pending-actions/{action_id}", response_model=Envelope[PendingActionOut])
async def get_pending(action_id: uuid.UUID, svc: ApprSvc):
    return Envelope(data=out(await svc.get(action_id)))


@router.post("/pending-actions/{action_id}/approve", response_model=Envelope[PendingActionOut], dependencies=[Depends(forbid_demo)])
async def approve(action_id: uuid.UUID, body: DecisionIn, admin: CurrentUser, svc: ApprSvc, ctx: RequestContextDep):
    """Approving executes the action as YOU, through the normal service rules. The requester cannot approve their own request."""
    return Envelope(data=out(await svc.approve(admin, action_id, body.reason, ctx)))


@router.post("/pending-actions/{action_id}/reject", response_model=Envelope[PendingActionOut], dependencies=[Depends(forbid_demo)])
async def reject(action_id: uuid.UUID, body: DecisionIn, admin: CurrentUser, svc: ApprSvc, ctx: RequestContextDep):
    return Envelope(data=out(await svc.reject(admin, action_id, body.reason, ctx)))


# ------------------------------------------------------------------ Agent Control Center (observability; read-only)
from app.models.enums import AgentName, AgentStatus  # noqa: E402
from app.schemas.agents import AgentDetailOut, ControlCenterOut, ExecutionOut, ExecutionPage  # noqa: E402
from app.services.agent_observability import AgentObservabilityService  # noqa: E402


def _obs(session: SessionDep, settings: SettingsDep) -> AgentObservabilityService:
    return AgentObservabilityService(session, settings)


ObsSvc = Annotated[AgentObservabilityService, Depends(_obs)]
Days = Annotated[int, Query(ge=1, le=365)]


@router.get("/agents", response_model=Envelope[ControlCenterOut])
async def control_center(svc: ObsSvc, days: Days = 30):
    """One card per agent: counts, success/failure/review, average duration, providers, fallback use, last run, health."""
    return Envelope(data=await svc.control_center(days))


@router.get("/agents/{agent}", response_model=Envelope[AgentDetailOut])
async def agent_detail(agent: AgentName, svc: ObsSvc, days: Days = 30, recent: Annotated[int, Query(ge=1, le=50)] = 10):
    return Envelope(data=await svc.agent_detail(agent, days, recent))


@router.get("/agent-executions", response_model=Envelope[ExecutionPage])
async def list_executions(svc: ObsSvc, agent: AgentName | None = None, status: AgentStatus | None = None,
                          trigger_type: Annotated[str | None, Query(max_length=60)] = None,
                          entity_type: Annotated[str | None, Query(max_length=50)] = None,
                          entity_id: Annotated[str | None, Query(max_length=64)] = None, stuck: bool = False,
                          days: Annotated[int | None, Query(ge=1, le=365)] = None, cursor: Cursor = None, limit: Limit = 20):
    return Envelope(data=await svc.executions(agent, status, trigger_type, entity_type, entity_id, stuck, days, cursor, limit))


@router.get("/agent-executions/{execution_id}", response_model=Envelope[ExecutionOut])
async def get_execution(execution_id: uuid.UUID, svc: ObsSvc):
    return Envelope(data=await svc.execution(execution_id))


# ------------------------------------------------------------------ Worker / sweeper status (Stage 18)
from app.core.dependencies import RedisDep  # noqa: E402
from app.services.recovery import read_worker_status  # noqa: E402
from app.workers.maintenance_jobs import SWEEPERS  # noqa: E402


@router.get("/workers", response_model=Envelope[WorkerStatusOut])
async def worker_status(redis: RedisDep):
    """Worker liveness (heartbeat age) plus the last result of every recovery sweeper."""
    return Envelope(data=await read_worker_status(redis, list(SWEEPERS)))
