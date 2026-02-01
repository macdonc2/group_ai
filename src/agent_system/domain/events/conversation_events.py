"""Conversation-related domain events."""

from agent_system.domain.events.base import DomainEvent
from agent_system.domain.value_objects import ConversationId, MessageRole, UserId


class ConversationCreated(DomainEvent):
    """Event raised when a new conversation is created."""

    conversation_id: ConversationId
    user_id: UserId
    title: str | None = None


class MessageAdded(DomainEvent):
    """Event raised when a message is added to a conversation."""

    conversation_id: ConversationId
    user_id: UserId
    message_role: MessageRole
    content_preview: str  # Truncated content for logging
    token_count: int = 0


class ConversationArchived(DomainEvent):
    """Event raised when a conversation is archived."""

    conversation_id: ConversationId
    user_id: UserId


class PlanAttached(DomainEvent):
    """Event raised when a plan is attached to a conversation."""

    conversation_id: ConversationId
    plan_id: str
    user_id: UserId
