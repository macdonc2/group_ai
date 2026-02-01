"""Domain events - Events for meaningful state changes."""

from agent_system.domain.events.base import DomainEvent
from agent_system.domain.events.conversation_events import (
    ConversationArchived,
    ConversationCreated,
    MessageAdded,
    PlanAttached,
)
from agent_system.domain.events.knowledge_events import (
    IntentExtracted,
    KnowledgeNodeCreated,
    RelationshipCreated,
    SuggestionGenerated,
)
from agent_system.domain.events.plan_events import (
    PlanCompleted,
    PlanCreated,
    PlanStatusChanged,
    PlanStepCompleted,
    PlanStepStarted,
)

__all__ = [
    # Base
    "DomainEvent",
    # Conversation Events
    "ConversationCreated",
    "MessageAdded",
    "ConversationArchived",
    "PlanAttached",
    # Plan Events
    "PlanCreated",
    "PlanStatusChanged",
    "PlanStepStarted",
    "PlanStepCompleted",
    "PlanCompleted",
    # Knowledge Events
    "KnowledgeNodeCreated",
    "RelationshipCreated",
    "IntentExtracted",
    "SuggestionGenerated",
]
