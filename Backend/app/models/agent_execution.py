import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, pg_enum, uuid_pk
from app.models.enums import AgentName, AgentStatus


class AgentExecution(Base):
    """One event-driven agent run. Stores ONLY safe operational metadata (never prompts / chain-of-thought).
    `id` doubles as the frontend jobId. idempotency_key makes event delivery at-least-once safe."""
    __tablename__ = "agent_executions"
    __table_args__ = (Index("ix_agent_executions_agent_created", "agent_name", "created_at"),
                      Index("ix_agent_executions_entity", "related_entity_type", "related_entity_id"))

    id: Mapped[uuid.UUID] = uuid_pk()
    agent_name: Mapped[AgentName] = mapped_column(pg_enum(AgentName))
    trigger_type: Mapped[str] = mapped_column(String(60))
    status: Mapped[AgentStatus] = mapped_column(pg_enum(AgentStatus), default=AgentStatus.QUEUED, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    related_entity_type: Mapped[str | None] = mapped_column(String(50))
    related_entity_id: Mapped[str | None] = mapped_column(String(64))
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    provider: Mapped[str | None] = mapped_column(String(40))
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    summary: Mapped[str | None] = mapped_column(Text)
    tool_calls: Mapped[list] = mapped_column(JSONB, default=list)  # [{"tool": "market_search", "ok": true, "n": 5}]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
