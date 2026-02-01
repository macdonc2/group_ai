"""Group-related domain entities for collaborative conversations."""

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field

from agent_system.domain.value_objects import (
    GroupConversationId,
    GroupId,
    GroupMembershipId,
    MessageId,
    UserId,
)
from agent_system.domain.value_objects.message import Message


class MemberRole(str, Enum):
    """Role of a member in a group."""

    OWNER = "owner"  # Group creator with full permissions
    MEMBER = "member"  # Regular member


class GroupMembership(BaseModel):
    """Represents a user's membership in a group."""

    id: GroupMembershipId
    user_id: UserId
    group_id: GroupId
    role: MemberRole = MemberRole.MEMBER
    sharing_enabled: Annotated[bool, Field(default=True, description="Whether user's data is included in shared history/analytics")]
    joined_at: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    last_seen_at: datetime | None = None

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, GroupMembership):
            return self.id == other.id
        return False

    @classmethod
    def create(
        cls, 
        user_id: UserId, 
        group_id: GroupId, 
        role: MemberRole = MemberRole.MEMBER,
    ) -> "GroupMembership":
        """Create a new group membership."""
        return cls(
            id=GroupMembershipId.generate(),
            user_id=user_id,
            group_id=group_id,
            role=role,
        )

    def update_last_seen(self) -> "GroupMembership":
        """Update the last seen timestamp."""
        return self.model_copy(update={"last_seen_at": datetime.utcnow()})

    def toggle_sharing(self, enabled: bool) -> "GroupMembership":
        """Toggle sharing preference for privacy control."""
        return self.model_copy(update={"sharing_enabled": enabled})


class Group(BaseModel):
    """A peer-based group for collaborative conversations."""

    id: GroupId
    name: Annotated[str, Field(min_length=1, max_length=255)]
    description: str | None = None
    created_by: UserId
    members: Annotated[list[GroupMembership], Field(default_factory=list)]
    created_at: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    updated_at: Annotated[datetime, Field(default_factory=datetime.utcnow)]

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Group):
            return self.id == other.id
        return False

    @classmethod
    def create(cls, name: str, created_by: UserId, description: str | None = None) -> "Group":
        """Create a new group with the creator as the owner."""
        group_id = GroupId.generate()
        creator_membership = GroupMembership.create(
            user_id=created_by, 
            group_id=group_id, 
            role=MemberRole.OWNER,
        )
        
        return cls(
            id=group_id,
            name=name,
            description=description,
            created_by=created_by,
            members=[creator_membership],
        )

    def add_member(self, user_id: UserId) -> "Group":
        """Add a new member to the group (any member can add in peer model)."""
        # Check if user is already a member
        if any(m.user_id == user_id for m in self.members):
            return self  # Already a member
        
        new_membership = GroupMembership.create(user_id=user_id, group_id=self.id)
        return self.model_copy(
            update={
                "members": [*self.members, new_membership],
                "updated_at": datetime.utcnow(),
            }
        )

    def remove_member(self, user_id: UserId) -> "Group":
        """Remove a member from the group."""
        updated_members = [m for m in self.members if m.user_id != user_id]
        return self.model_copy(
            update={
                "members": updated_members,
                "updated_at": datetime.utcnow(),
            }
        )

    def get_member(self, user_id: UserId) -> GroupMembership | None:
        """Get a specific member's membership."""
        for member in self.members:
            if member.user_id == user_id:
                return member
        return None

    def is_member(self, user_id: UserId) -> bool:
        """Check if a user is a member of the group."""
        return any(m.user_id == user_id for m in self.members)

    def is_owner(self, user_id: UserId) -> bool:
        """Check if a user is the owner of the group."""
        for member in self.members:
            if member.user_id == user_id and member.role == MemberRole.OWNER:
                return True
        return False

    def get_sharing_members(self) -> list[GroupMembership]:
        """Get members who have sharing enabled (for privacy-respecting queries)."""
        return [m for m in self.members if m.sharing_enabled]

    def update_member(self, membership: GroupMembership) -> "Group":
        """Update a member's membership details."""
        updated_members = [
            membership if m.user_id == membership.user_id else m
            for m in self.members
        ]
        return self.model_copy(
            update={
                "members": updated_members,
                "updated_at": datetime.utcnow(),
            }
        )

    def update_info(self, name: str | None = None, description: str | None = None) -> "Group":
        """Update group name and/or description."""
        updates = {"updated_at": datetime.utcnow()}
        if name is not None:
            updates["name"] = name
        if description is not None:
            updates["description"] = description
        return self.model_copy(update=updates)

    @property
    def member_count(self) -> int:
        """Get the number of members in the group."""
        return len(self.members)

    @property
    def member_ids(self) -> list[UserId]:
        """Get list of all member user IDs."""
        return [m.user_id for m in self.members]


class StoredGroupMessage(BaseModel):
    """A message stored in a group conversation with metadata."""

    id: MessageId
    message: Message
    sender_id: UserId
    token_count: int = 0

    @classmethod
    def create(cls, message: Message, sender_id: UserId, token_count: int = 0) -> "StoredGroupMessage":
        """Create a stored group message."""
        return cls(
            id=MessageId.generate(),
            message=message,
            sender_id=sender_id,
            token_count=token_count,
        )


class GroupConversationMetadata(BaseModel):
    """Metadata for a group conversation."""

    title: str | None = None
    summary: str | None = None
    tags: Annotated[list[str], Field(default_factory=list)]
    topic_keywords: Annotated[list[str], Field(default_factory=list)]
    total_tokens_used: int = 0


class GroupConversation(BaseModel):
    """A conversation within a group, shared among all members."""

    id: GroupConversationId
    group_id: GroupId
    messages: Annotated[list[StoredGroupMessage], Field(default_factory=list)]
    participant_ids: Annotated[list[UserId], Field(default_factory=list, description="Users who have contributed to this conversation")]
    metadata: Annotated[GroupConversationMetadata, Field(default_factory=GroupConversationMetadata)]
    context_window_size: int = 20
    created_at: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    updated_at: Annotated[datetime, Field(default_factory=datetime.utcnow)]

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, GroupConversation):
            return self.id == other.id
        return False

    @classmethod
    def create(cls, group_id: GroupId, title: str | None = None) -> "GroupConversation":
        """Create a new group conversation."""
        metadata = GroupConversationMetadata(title=title)
        return cls(
            id=GroupConversationId.generate(),
            group_id=group_id,
            metadata=metadata,
        )

    def add_message(self, message: Message, sender_id: UserId, token_count: int = 0) -> "GroupConversation":
        """Add a message to the conversation."""
        stored = StoredGroupMessage.create(message, sender_id, token_count)
        
        # Track participants
        updated_participants = list(self.participant_ids)
        if sender_id not in updated_participants:
            updated_participants.append(sender_id)
        
        # Update token count
        new_total = self.metadata.total_tokens_used + token_count
        updated_metadata = self.metadata.model_copy(update={"total_tokens_used": new_total})
        
        return self.model_copy(
            update={
                "messages": [*self.messages, stored],
                "participant_ids": updated_participants,
                "metadata": updated_metadata,
                "updated_at": datetime.utcnow(),
            }
        )

    def get_context_messages(self) -> list[Message]:
        """Get recent messages for context window."""
        recent = self.messages[-self.context_window_size:]
        return [stored.message for stored in recent]

    def get_all_messages(self) -> list[Message]:
        """Get all messages in the conversation."""
        return [stored.message for stored in self.messages]

    def update_metadata(self, **kwargs) -> "GroupConversation":
        """Update conversation metadata."""
        updated_metadata = self.metadata.model_copy(update=kwargs)
        return self.model_copy(
            update={
                "metadata": updated_metadata,
                "updated_at": datetime.utcnow(),
            }
        )

    @property
    def message_count(self) -> int:
        """Get the number of messages in the conversation."""
        return len(self.messages)

    @property
    def last_message(self) -> StoredGroupMessage | None:
        """Get the last message in the conversation."""
        return self.messages[-1] if self.messages else None
