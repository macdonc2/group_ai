"""Domain entities - Core business objects with identity and lifecycle."""

from agent_system.domain.entities.conversation import (
    Conversation,
    ConversationMetadata,
    StoredMessage,
)
from agent_system.domain.entities.calendar_event import (
    CalendarEvent,
    CalendarEventSource,
    CalendarSyncStatus,
)
from agent_system.domain.entities.extracted_event import (
    EventType,
    ExtractedEvent,
    GoogleCalendarSyncStatus,
)
from agent_system.domain.entities.group import (
    Group,
    GroupConversation,
    GroupConversationMetadata,
    GroupMembership,
    MemberRole,
    StoredGroupMessage,
)
from agent_system.domain.entities.knowledge import (
    KnowledgeGraph,
    KnowledgeNode,
    KnowledgeNodeType,
)
from agent_system.domain.entities.plan import Plan, StoredPlanStep
from agent_system.domain.entities.social import (
    Contradiction,
    Expertise,
    Location,
    Pattern,
    Person,
    Pet,
    Preference,
    Thread,
)
from agent_system.domain.entities.user import LearnedPattern, User, UserPreferences

__all__ = [
    # User
    "User",
    "UserPreferences",
    "LearnedPattern",
    # Conversation
    "Conversation",
    "ConversationMetadata",
    "StoredMessage",
    # Group
    "Group",
    "GroupMembership",
    "MemberRole",
    "GroupConversation",
    "GroupConversationMetadata",
    "StoredGroupMessage",
    # Events
    "ExtractedEvent",
    "EventType",
    "GoogleCalendarSyncStatus",
    # Calendar
    "CalendarEvent",
    "CalendarEventSource",
    "CalendarSyncStatus",
    # Plan
    "Plan",
    "StoredPlanStep",
    # Knowledge
    "KnowledgeNode",
    "KnowledgeNodeType",
    "KnowledgeGraph",
    # Social Graph
    "Person",
    "Pet",
    "Location",
    "Pattern",
    "Thread",
    "Expertise",
    "Preference",
    "Contradiction",
]
