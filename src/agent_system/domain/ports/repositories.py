"""Repository port interfaces for persistence."""

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from agent_system.domain.entities import Conversation, Plan, User
from agent_system.domain.value_objects import ConversationId, PlanId, UserId

T = TypeVar("T")
IdT = TypeVar("IdT")


class Repository(ABC, Generic[T, IdT]):
    """Base repository interface."""

    @abstractmethod
    async def get(self, id: IdT) -> T | None:
        """Get an entity by ID."""
        ...

    @abstractmethod
    async def save(self, entity: T) -> T:
        """Save an entity."""
        ...

    @abstractmethod
    async def delete(self, id: IdT) -> bool:
        """Delete an entity by ID."""
        ...

    @abstractmethod
    async def exists(self, id: IdT) -> bool:
        """Check if an entity exists."""
        ...


class UserRepository(Repository[User, UserId], ABC):
    """Repository interface for User entities."""

    @abstractmethod
    async def get_by_email(self, email: str) -> User | None:
        """Get a user by email address."""
        ...

    @abstractmethod
    async def list_active(self, limit: int = 100, offset: int = 0) -> list[User]:
        """List active users with pagination."""
        ...

    @abstractmethod
    async def update(self, user: User) -> User:
        """Update an existing user."""
        ...


class ConversationRepository(Repository[Conversation, ConversationId], ABC):
    """Repository interface for Conversation entities."""

    @abstractmethod
    async def get_by_user(
        self,
        user_id: UserId,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Conversation]:
        """Get conversations for a user."""
        ...

    @abstractmethod
    async def get_active_for_user(self, user_id: UserId) -> Conversation | None:
        """Get the most recent active conversation for a user."""
        ...

    @abstractmethod
    async def update(self, conversation: Conversation) -> Conversation:
        """Update an existing conversation."""
        ...

    @abstractmethod
    async def archive(self, conversation_id: ConversationId) -> bool:
        """Archive a conversation."""
        ...


class PlanRepository(Repository[Plan, PlanId], ABC):
    """Repository interface for Plan entities."""

    @abstractmethod
    async def get_by_user(
        self,
        user_id: UserId,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Plan]:
        """Get plans for a user."""
        ...

    @abstractmethod
    async def get_by_conversation(
        self,
        conversation_id: ConversationId,
    ) -> list[Plan]:
        """Get plans for a conversation."""
        ...

    @abstractmethod
    async def get_active_for_conversation(
        self,
        conversation_id: ConversationId,
    ) -> Plan | None:
        """Get the active plan for a conversation."""
        ...

    @abstractmethod
    async def update(self, plan: Plan) -> Plan:
        """Update an existing plan."""
        ...
