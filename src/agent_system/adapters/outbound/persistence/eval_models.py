"""SQLAlchemy models for turn traces and eval runs.

Imported from `persistence/__init__.py` so `Base.metadata.create_all` at
startup creates the tables; there is no migration tool in this project, so
these are new tables rather than new columns on existing ones.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from agent_system.adapters.outbound.persistence.database import Base


class TurnTraceModel(Base):
    """One traced agent turn from real traffic (chat or group chat)."""

    __tablename__ = "turn_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)
    message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="chat")  # chat | group
    user_input: Mapped[str] = mapped_column(Text, default="")
    path: Mapped[list[str]] = mapped_column(JSON, default=list)
    trace: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    total_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class EvalRunModel(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    suite: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | complete | failed
    judge: Mapped[str] = mapped_column(String(16), default="openai")  # openai | jev | both | none
    git_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # {"pass_rate", "cases", "passed", "deterministic": {...}, "judge": {judge: {dim: mean}},
    #  "agreement": {...}, "latency": {...}, "cost": {...}, "failure_counts": {...}}
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    failure_analysis_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EvalCaseResultModel(Base):
    __tablename__ = "eval_case_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("eval_runs.id", ondelete="CASCADE"), index=True
    )
    case_id: Mapped[str] = mapped_column(String(128), index=True)
    repeat: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    failure_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    case: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # the dataset case, for display
    scores: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # deterministic scorer output
    judgements: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # {judge: {rubric: {dims, rationale}}}
    turns: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # [{user, response, trace}]
    total_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    judge_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
