"""Plan entity - represents a multi-step plan for achieving a goal."""

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field

from agent_system.domain.value_objects import (
    ConversationId,
    PlanGoal,
    PlanId,
    PlanStatus,
    PlanStep,
    PlanStepId,
    StepStatus,
    UserId,
)


class StoredPlanStep(BaseModel):
    """A plan step with its identifier."""

    id: PlanStepId
    step: PlanStep

    @classmethod
    def create(cls, step: PlanStep) -> "StoredPlanStep":
        """Create a new stored plan step."""
        return cls(id=PlanStepId.generate(), step=step)


class Plan(BaseModel):
    """Plan entity for tracking multi-step task execution."""

    id: PlanId
    user_id: UserId
    conversation_id: ConversationId
    goal: PlanGoal
    steps: Annotated[list[StoredPlanStep], Field(default_factory=list)]
    status: Annotated[PlanStatus, Field(default=PlanStatus.DRAFT)]
    current_step_index: int = 0
    created_at: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    updated_at: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    completed_at: datetime | None = None
    metadata: Annotated[dict[str, Any], Field(default_factory=dict)]

    @classmethod
    def create(
        cls,
        user_id: UserId,
        conversation_id: ConversationId,
        goal: PlanGoal,
        steps: list[PlanStep] | None = None,
    ) -> "Plan":
        """Create a new plan."""
        stored_steps = [StoredPlanStep.create(step) for step in (steps or [])]
        return cls(
            id=PlanId.generate(),
            user_id=user_id,
            conversation_id=conversation_id,
            goal=goal,
            steps=stored_steps,
        )

    def add_step(self, step: PlanStep) -> "Plan":
        """Add a step to the plan."""
        stored = StoredPlanStep.create(step)
        steps = [*self.steps, stored]
        return self.model_copy(
            update={
                "steps": steps,
                "updated_at": datetime.utcnow(),
            }
        )

    def add_steps(self, steps: list[PlanStep]) -> "Plan":
        """Add multiple steps to the plan."""
        stored_steps = [StoredPlanStep.create(step) for step in steps]
        all_steps = [*self.steps, *stored_steps]
        return self.model_copy(
            update={
                "steps": all_steps,
                "updated_at": datetime.utcnow(),
            }
        )

    def activate(self) -> "Plan":
        """Activate the plan."""
        return self.model_copy(
            update={
                "status": PlanStatus.ACTIVE,
                "updated_at": datetime.utcnow(),
            }
        )

    def pause(self) -> "Plan":
        """Pause the plan."""
        return self.model_copy(
            update={
                "status": PlanStatus.PAUSED,
                "updated_at": datetime.utcnow(),
            }
        )

    def resume(self) -> "Plan":
        """Resume a paused plan."""
        if self.status != PlanStatus.PAUSED:
            return self
        return self.model_copy(
            update={
                "status": PlanStatus.ACTIVE,
                "updated_at": datetime.utcnow(),
            }
        )

    def complete(self) -> "Plan":
        """Mark the plan as completed."""
        now = datetime.utcnow()
        return self.model_copy(
            update={
                "status": PlanStatus.COMPLETED,
                "updated_at": now,
                "completed_at": now,
            }
        )

    def cancel(self) -> "Plan":
        """Cancel the plan."""
        return self.model_copy(
            update={
                "status": PlanStatus.CANCELLED,
                "updated_at": datetime.utcnow(),
            }
        )

    def fail(self, reason: str | None = None) -> "Plan":
        """Mark the plan as failed."""
        metadata = {**self.metadata, "failure_reason": reason} if reason else self.metadata
        return self.model_copy(
            update={
                "status": PlanStatus.FAILED,
                "metadata": metadata,
                "updated_at": datetime.utcnow(),
            }
        )

    def update_step(self, step_index: int, updated_step: PlanStep) -> "Plan":
        """Update a specific step."""
        if step_index < 0 or step_index >= len(self.steps):
            return self
        
        steps = list(self.steps)
        steps[step_index] = StoredPlanStep(
            id=self.steps[step_index].id,
            step=updated_step,
        )
        return self.model_copy(
            update={
                "steps": steps,
                "updated_at": datetime.utcnow(),
            }
        )

    def start_current_step(self) -> "Plan":
        """Start the current step."""
        if self.current_step_index >= len(self.steps):
            return self
        
        current = self.steps[self.current_step_index]
        updated_step = current.step.start()
        return self.update_step(self.current_step_index, updated_step)

    def complete_current_step(self, result: str) -> "Plan":
        """Complete the current step and advance."""
        if self.current_step_index >= len(self.steps):
            return self
        
        current = self.steps[self.current_step_index]
        updated_step = current.step.complete(result)
        plan = self.update_step(self.current_step_index, updated_step)
        
        # Advance to next step
        new_index = self.current_step_index + 1
        plan = plan.model_copy(update={"current_step_index": new_index})
        
        # Check if plan is complete
        if new_index >= len(self.steps):
            plan = plan.complete()
        
        return plan

    def fail_current_step(self, error: str) -> "Plan":
        """Fail the current step."""
        if self.current_step_index >= len(self.steps):
            return self
        
        current = self.steps[self.current_step_index]
        updated_step = current.step.fail(error)
        return self.update_step(self.current_step_index, updated_step)

    @property
    def current_step(self) -> StoredPlanStep | None:
        """Get the current step."""
        if 0 <= self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None

    @property
    def completed_step_indices(self) -> set[int]:
        """Get indices of completed steps."""
        return {
            i for i, stored in enumerate(self.steps)
            if stored.step.status == StepStatus.COMPLETED
        }

    @property
    def progress(self) -> float:
        """Get completion progress as a percentage."""
        if not self.steps:
            return 0.0
        completed = len(self.completed_step_indices)
        return (completed / len(self.steps)) * 100

    @property
    def is_active(self) -> bool:
        """Check if the plan is active."""
        return self.status == PlanStatus.ACTIVE

    @property
    def is_complete(self) -> bool:
        """Check if the plan is complete."""
        return self.status == PlanStatus.COMPLETED
