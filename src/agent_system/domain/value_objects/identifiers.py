"""Identifier value objects for domain entities."""

from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class UserId(BaseModel):
    """User identifier value object."""

    value: Annotated[UUID, Field(default_factory=uuid4)]

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, UserId):
            return self.value == other.value
        return False

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def generate(cls) -> "UserId":
        """Generate a new user ID."""
        return cls(value=uuid4())

    @classmethod
    def from_string(cls, value: str) -> "UserId":
        """Create user ID from string."""
        return cls(value=UUID(value))


class ConversationId(BaseModel):
    """Conversation identifier value object."""

    value: Annotated[UUID, Field(default_factory=uuid4)]

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ConversationId):
            return self.value == other.value
        return False

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def generate(cls) -> "ConversationId":
        """Generate a new conversation ID."""
        return cls(value=uuid4())

    @classmethod
    def from_string(cls, value: str) -> "ConversationId":
        """Create conversation ID from string."""
        return cls(value=UUID(value))


class MessageId(BaseModel):
    """Message identifier value object."""

    value: Annotated[UUID, Field(default_factory=uuid4)]

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, MessageId):
            return self.value == other.value
        return False

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def generate(cls) -> "MessageId":
        """Generate a new message ID."""
        return cls(value=uuid4())

    @classmethod
    def from_string(cls, value: str) -> "MessageId":
        """Create message ID from string."""
        return cls(value=UUID(value))


class PlanId(BaseModel):
    """Plan identifier value object."""

    value: Annotated[UUID, Field(default_factory=uuid4)]

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, PlanId):
            return self.value == other.value
        return False

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def generate(cls) -> "PlanId":
        """Generate a new plan ID."""
        return cls(value=uuid4())

    @classmethod
    def from_string(cls, value: str) -> "PlanId":
        """Create plan ID from string."""
        return cls(value=UUID(value))


class PlanStepId(BaseModel):
    """Plan step identifier value object."""

    value: Annotated[UUID, Field(default_factory=uuid4)]

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, PlanStepId):
            return self.value == other.value
        return False

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def generate(cls) -> "PlanStepId":
        """Generate a new plan step ID."""
        return cls(value=uuid4())

    @classmethod
    def from_string(cls, value: str) -> "PlanStepId":
        """Create plan step ID from string."""
        return cls(value=UUID(value))


class KnowledgeNodeId(BaseModel):
    """Knowledge node identifier value object."""

    value: Annotated[UUID, Field(default_factory=uuid4)]

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, KnowledgeNodeId):
            return self.value == other.value
        return False

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def generate(cls) -> "KnowledgeNodeId":
        """Generate a new knowledge node ID."""
        return cls(value=uuid4())

    @classmethod
    def from_string(cls, value: str) -> "KnowledgeNodeId":
        """Create knowledge node ID from string."""
        return cls(value=UUID(value))


class GroupId(BaseModel):
    """Group identifier value object."""

    value: Annotated[UUID, Field(default_factory=uuid4)]

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, GroupId):
            return self.value == other.value
        return False

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def generate(cls) -> "GroupId":
        """Generate a new group ID."""
        return cls(value=uuid4())

    @classmethod
    def from_string(cls, value: str) -> "GroupId":
        """Create group ID from string."""
        return cls(value=UUID(value))


class GroupMembershipId(BaseModel):
    """Group membership identifier value object."""

    value: Annotated[UUID, Field(default_factory=uuid4)]

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, GroupMembershipId):
            return self.value == other.value
        return False

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def generate(cls) -> "GroupMembershipId":
        """Generate a new group membership ID."""
        return cls(value=uuid4())

    @classmethod
    def from_string(cls, value: str) -> "GroupMembershipId":
        """Create group membership ID from string."""
        return cls(value=UUID(value))


class GroupConversationId(BaseModel):
    """Group conversation identifier value object."""

    value: Annotated[UUID, Field(default_factory=uuid4)]

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, GroupConversationId):
            return self.value == other.value
        return False

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def generate(cls) -> "GroupConversationId":
        """Generate a new group conversation ID."""
        return cls(value=uuid4())

    @classmethod
    def from_string(cls, value: str) -> "GroupConversationId":
        """Create group conversation ID from string."""
        return cls(value=UUID(value))


class EventId(BaseModel):
    """Extracted event identifier value object."""

    value: Annotated[UUID, Field(default_factory=uuid4)]

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, EventId):
            return self.value == other.value
        return False

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def generate(cls) -> "EventId":
        """Generate a new event ID."""
        return cls(value=uuid4())

    @classmethod
    def from_string(cls, value: str) -> "EventId":
        """Create event ID from string."""
        return cls(value=UUID(value))
