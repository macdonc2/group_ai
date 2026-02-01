"""Conversation entity - represents a conversation session with history."""

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field

from agent_system.domain.value_objects import (
    ConversationId,
    Message,
    MessageId,
    PlanId,
    UserId,
)


class ConversationMetadata(BaseModel):
    """Metadata about a conversation."""

    title: str | None = None
    summary: str | None = None
    tags: Annotated[list[str], Field(default_factory=list)]
    topic_keywords: Annotated[list[str], Field(default_factory=list)]
    total_tokens_used: int = 0
    custom_data: Annotated[dict[str, Any], Field(default_factory=dict)]


class StoredMessage(BaseModel):
    """A message stored in conversation history."""

    id: MessageId
    message: Message
    token_count: int = 0

    @classmethod
    def create(cls, message: Message, token_count: int = 0) -> "StoredMessage":
        """Create a new stored message."""
        return cls(
            id=MessageId.generate(),
            message=message,
            token_count=token_count,
        )


class Conversation(BaseModel):
    """Conversation entity managing message history and context."""

    id: ConversationId
    user_id: UserId
    messages: Annotated[list[StoredMessage], Field(default_factory=list)]
    active_plan_id: PlanId | None = None
    metadata: Annotated[ConversationMetadata, Field(default_factory=ConversationMetadata)]
    context_window_size: int = 20  # Number of recent messages to include in context
    created_at: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    updated_at: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    is_archived: bool = False

    @classmethod
    def create(cls, user_id: UserId, title: str | None = None) -> "Conversation":
        """Create a new conversation."""
        return cls(
            id=ConversationId.generate(),
            user_id=user_id,
            metadata=ConversationMetadata(title=title),
        )

    def add_message(self, message: Message, token_count: int = 0) -> "Conversation":
        """Add a message to the conversation."""
        stored = StoredMessage.create(message, token_count)
        messages = [*self.messages, stored]
        metadata = self.metadata.model_copy(
            update={"total_tokens_used": self.metadata.total_tokens_used + token_count}
        )
        return self.model_copy(
            update={
                "messages": messages,
                "metadata": metadata,
                "updated_at": datetime.utcnow(),
            }
        )

    def get_context_messages(self) -> list[Message]:
        """Get recent messages for context window."""
        recent = self.messages[-self.context_window_size :]
        return [stored.message for stored in recent]

    def get_all_messages(self) -> list[Message]:
        """Get all messages in the conversation."""
        return [stored.message for stored in self.messages]

    def set_active_plan(self, plan_id: PlanId) -> "Conversation":
        """Set the active plan for this conversation."""
        return self.model_copy(
            update={
                "active_plan_id": plan_id,
                "updated_at": datetime.utcnow(),
            }
        )

    def clear_active_plan(self) -> "Conversation":
        """Clear the active plan."""
        return self.model_copy(
            update={
                "active_plan_id": None,
                "updated_at": datetime.utcnow(),
            }
        )

    def update_metadata(self, **kwargs: Any) -> "Conversation":
        """Update conversation metadata."""
        new_metadata = self.metadata.model_copy(update=kwargs)
        return self.model_copy(
            update={
                "metadata": new_metadata,
                "updated_at": datetime.utcnow(),
            }
        )

    def archive(self) -> "Conversation":
        """Archive the conversation."""
        return self.model_copy(
            update={
                "is_archived": True,
                "updated_at": datetime.utcnow(),
            }
        )

    def unarchive(self) -> "Conversation":
        """Unarchive the conversation."""
        return self.model_copy(
            update={
                "is_archived": False,
                "updated_at": datetime.utcnow(),
            }
        )

    @property
    def message_count(self) -> int:
        """Get the number of messages."""
        return len(self.messages)

    @property
    def last_message(self) -> StoredMessage | None:
        """Get the last message."""
        return self.messages[-1] if self.messages else None
