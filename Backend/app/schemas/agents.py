import uuid
from datetime import datetime
from typing import Literal

from pydantic import ConfigDict

from app.models.enums import AgentName, AgentStatus
from app.schemas.common import CamelBlobList, CamelModel


class ExecutionOut(CamelModel):
    """Safe operational metadata only: no prompts, transcripts or reasoning are ever stored."""
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    agent_name: AgentName
    trigger_type: str
    status: AgentStatus
    attempt: int
    provider: str | None
    fallback_used: bool
    error_code: str | None
    summary: str | None
    tool_calls: CamelBlobList
    related_entity_type: str | None
    related_entity_id: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None


class ExecutionPage(CamelModel):
    items: list[ExecutionOut]
    next_cursor: str | None


class LastExecution(CamelModel):
    id: uuid.UUID
    status: AgentStatus
    trigger_type: str
    summary: str | None
    at: datetime


class AgentSummaryOut(CamelModel):
    agent: AgentName
    display_name: str
    mode: Literal["event_driven"] = "event_driven"  # agents run on events; they are NOT 24/7 processes
    window_days: int
    total_executions: int          # inside the window
    total_executions_all_time: int
    success_count: int             # COMPLETED
    failed_count: int
    review_required_count: int
    in_flight_count: int           # QUEUED + RUNNING
    stuck_count: int               # QUEUED/RUNNING for longer than AGENT_STUCK_MINUTES
    success_rate: float | None     # success / (success + failed + review_required); None when nothing finished
    avg_duration_ms: int | None
    fallback_count: int
    fallback_rate: float | None
    providers: dict[str, int]
    triggers: dict[str, int]
    last_execution: LastExecution | None
    health: Literal["idle", "ok", "attention"]
    health_reason: str | None


class AgentDetailOut(CamelModel):
    summary: AgentSummaryOut
    top_error_codes: dict[str, int]
    recent: list[ExecutionOut]


class ControlCenterOut(CamelModel):
    generated_at: datetime
    agents: list[AgentSummaryOut]
