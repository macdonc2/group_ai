"""Message-related value objects."""

from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    """Role of a message sender."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class MessageContent(BaseModel):
    """Message content value object."""

    text: str
    metadata: Annotated[dict[str, Any], Field(default_factory=dict)]

    def __str__(self) -> str:
        return self.text

    def is_empty(self) -> bool:
        """Check if content is empty."""
        return not self.text.strip()

    def truncate(self, max_length: int) -> "MessageContent":
        """Return truncated content."""
        if len(self.text) <= max_length:
            return self
        return MessageContent(
            text=self.text[:max_length] + "...",
            metadata={**self.metadata, "truncated": True, "original_length": len(self.text)},
        )


class ToolCall(BaseModel):
    """Represents a tool call made by the assistant."""

    tool_name: str
    arguments: dict[str, Any]
    result: str | None = None


class Message(BaseModel):
    """Complete message value object with role and content."""

    role: MessageRole
    content: MessageContent
    tool_calls: Annotated[list[ToolCall], Field(default_factory=list)]
    timestamp: Annotated[datetime, Field(default_factory=datetime.utcnow)]

    @classmethod
    def user(cls, text: str) -> "Message":
        """Create a user message."""
        return cls(role=MessageRole.USER, content=MessageContent(text=text))

    @classmethod
    def assistant(
        cls, text: str, tool_calls: list[ToolCall] | None = None
    ) -> "Message":
        """Create an assistant message."""
        return cls(
            role=MessageRole.ASSISTANT,
            content=MessageContent(text=text),
            tool_calls=tool_calls or [],
        )

    @classmethod
    def system(cls, text: str) -> "Message":
        """Create a system message."""
        return cls(role=MessageRole.SYSTEM, content=MessageContent(text=text))

    @classmethod
    def tool(cls, text: str, tool_name: str) -> "Message":
        """Create a tool response message."""
        return cls(
            role=MessageRole.TOOL,
            content=MessageContent(text=text, metadata={"tool_name": tool_name}),
        )
