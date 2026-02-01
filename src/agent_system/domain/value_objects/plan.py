"""Plan-related value objects."""

from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, Field


class PlanStatus(str, Enum):
    """Status of a plan."""

    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class StepStatus(str, Enum):
    """Status of a plan step."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    BLOCKED = "blocked"


class PlanStep(BaseModel):
    """A single step in a plan."""

    description: str
    status: Annotated[StepStatus, Field(default=StepStatus.PENDING)]
    order: int
    dependencies: Annotated[list[int], Field(default_factory=list)]
    tool_required: str | None = None
    result: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: Annotated[dict[str, Any], Field(default_factory=dict)]

    def can_start(self, completed_steps: set[int]) -> bool:
        """Check if this step can start based on dependencies."""
        return all(dep in completed_steps for dep in self.dependencies)

    def start(self) -> "PlanStep":
        """Mark step as in progress."""
        return self.model_copy(
            update={"status": StepStatus.IN_PROGRESS, "started_at": datetime.utcnow()}
        )

    def complete(self, result: str) -> "PlanStep":
        """Mark step as completed."""
        return self.model_copy(
            update={
                "status": StepStatus.COMPLETED,
                "result": result,
                "completed_at": datetime.utcnow(),
            }
        )

    def fail(self, error: str) -> "PlanStep":
        """Mark step as failed."""
        return self.model_copy(
            update={
                "status": StepStatus.FAILED,
                "error": error,
                "completed_at": datetime.utcnow(),
            }
        )

    def skip(self, reason: str) -> "PlanStep":
        """Mark step as skipped."""
        return self.model_copy(
            update={
                "status": StepStatus.SKIPPED,
                "result": reason,
                "completed_at": datetime.utcnow(),
            }
        )


class PlanGoal(BaseModel):
    """Represents the high-level goal of a plan."""

    description: str
    success_criteria: list[str]
    context: Annotated[dict[str, Any], Field(default_factory=dict)]

    def is_achieved(self, results: list[str]) -> bool:
        """Check if goal is achieved based on results.
        
        This is a simplified check - actual implementation would
        involve LLM evaluation.
        """
        return len(results) >= len(self.success_criteria)
