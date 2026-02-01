"""Plan-related domain events."""

from agent_system.domain.events.base import DomainEvent
from agent_system.domain.value_objects import (
    ConversationId,
    PlanId,
    PlanStatus,
    StepStatus,
    UserId,
)


class PlanCreated(DomainEvent):
    """Event raised when a new plan is created."""

    plan_id: PlanId
    user_id: UserId
    conversation_id: ConversationId
    goal_description: str
    step_count: int


class PlanStatusChanged(DomainEvent):
    """Event raised when a plan's status changes."""

    plan_id: PlanId
    user_id: UserId
    old_status: PlanStatus
    new_status: PlanStatus


class PlanStepStarted(DomainEvent):
    """Event raised when a plan step is started."""

    plan_id: PlanId
    step_index: int
    step_description: str


class PlanStepCompleted(DomainEvent):
    """Event raised when a plan step is completed."""

    plan_id: PlanId
    step_index: int
    step_status: StepStatus
    result: str | None = None
    error: str | None = None


class PlanCompleted(DomainEvent):
    """Event raised when a plan is fully completed."""

    plan_id: PlanId
    user_id: UserId
    total_steps: int
    completed_steps: int
    skipped_steps: int
    failed_steps: int
