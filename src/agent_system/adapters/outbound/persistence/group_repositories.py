"""SQLAlchemy repository implementations for group-related entities."""

from datetime import datetime

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agent_system.adapters.outbound.persistence.mappers import (
    ExtractedEventMapper,
    GroupConversationMapper,
    GroupMapper,
    GroupMembershipMapper,
    GroupMessageMapper,
)
from agent_system.adapters.outbound.persistence.models import (
    ExtractedEventModel,
    GroupConversationModel,
    GroupMembershipModel,
    GroupMessageModel,
    GroupModel,
)
from agent_system.domain.entities import ExtractedEvent, Group, GroupConversation, GroupMembership
from agent_system.domain.value_objects import EventId, GroupConversationId, GroupId, UserId


class SQLAlchemyGroupRepository:
    """SQLAlchemy repository for Group entities."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with database session."""
        self._session = session

    async def get(self, id: GroupId) -> Group | None:
        """Get a group by ID."""
        result = await self._session.execute(
            select(GroupModel)
            .options(selectinload(GroupModel.memberships))
            .where(GroupModel.id == str(id))
        )
        model = result.scalar_one_or_none()
        return GroupMapper.to_entity(model) if model else None

    async def get_by_user(
        self,
        user_id: UserId,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Group]:
        """Get groups that a user is a member of."""
        # First find group IDs where user is a member
        membership_query = select(GroupMembershipModel.group_id).where(
            GroupMembershipModel.user_id == str(user_id)
        )
        
        result = await self._session.execute(
            select(GroupModel)
            .options(selectinload(GroupModel.memberships))
            .where(GroupModel.id.in_(membership_query))
            .order_by(GroupModel.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return [GroupMapper.to_entity(model) for model in result.scalars()]

    async def save(self, group: Group) -> Group:
        """Save a new group."""
        model = GroupMapper.to_model(group)
        self._session.add(model)
        
        # Save memberships
        for membership in group.members:
            membership_model = GroupMembershipMapper.to_model(membership)
            self._session.add(membership_model)
        
        await self._session.flush()
        return group

    async def update(self, group: Group) -> Group:
        """Update an existing group."""
        result = await self._session.execute(
            select(GroupModel)
            .options(selectinload(GroupModel.memberships))
            .where(GroupModel.id == str(group.id))
        )
        model = result.scalar_one_or_none()
        if model:
            GroupMapper.update_model(model, group)
            
            # Get existing membership IDs
            existing_membership_ids = {m.id for m in model.memberships}
            
            # Add new memberships and update existing ones
            for membership in group.members:
                if str(membership.id) in existing_membership_ids:
                    # Update existing membership
                    for m_model in model.memberships:
                        if m_model.id == str(membership.id):
                            GroupMembershipMapper.update_model(m_model, membership)
                            break
                else:
                    # Add new membership
                    membership_model = GroupMembershipMapper.to_model(membership)
                    self._session.add(membership_model)
            
            # Remove memberships that are no longer in the group
            current_membership_ids = {str(m.id) for m in group.members}
            for m_model in model.memberships:
                if m_model.id not in current_membership_ids:
                    await self._session.delete(m_model)
            
            await self._session.flush()
        return group

    async def delete(self, id: GroupId) -> bool:
        """Delete a group by ID."""
        result = await self._session.execute(
            select(GroupModel).where(GroupModel.id == str(id))
        )
        model = result.scalar_one_or_none()
        if model:
            await self._session.delete(model)
            await self._session.flush()
            return True
        return False

    async def exists(self, id: GroupId) -> bool:
        """Check if a group exists."""
        result = await self._session.execute(
            select(GroupModel.id).where(GroupModel.id == str(id))
        )
        return result.scalar_one_or_none() is not None

    async def is_member(self, group_id: GroupId, user_id: UserId) -> bool:
        """Check if a user is a member of a group."""
        result = await self._session.execute(
            select(GroupMembershipModel.id).where(
                and_(
                    GroupMembershipModel.group_id == str(group_id),
                    GroupMembershipModel.user_id == str(user_id),
                )
            )
        )
        return result.scalar_one_or_none() is not None

    async def get_sharing_member_ids(self, group_id: GroupId) -> list[UserId]:
        """Get IDs of members who have sharing enabled (for privacy-respecting queries)."""
        result = await self._session.execute(
            select(GroupMembershipModel.user_id).where(
                and_(
                    GroupMembershipModel.group_id == str(group_id),
                    GroupMembershipModel.sharing_enabled == True,
                )
            )
        )
        return [UserId.from_string(row[0]) for row in result.all()]


class SQLAlchemyGroupConversationRepository:
    """SQLAlchemy repository for GroupConversation entities."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with database session."""
        self._session = session

    async def get(self, id: GroupConversationId) -> GroupConversation | None:
        """Get a group conversation by ID."""
        result = await self._session.execute(
            select(GroupConversationModel)
            .options(selectinload(GroupConversationModel.messages))
            .where(GroupConversationModel.id == str(id))
        )
        model = result.scalar_one_or_none()
        return GroupConversationMapper.to_entity(model) if model else None

    async def get_by_group(
        self,
        group_id: GroupId,
        limit: int = 50,
        offset: int = 0,
    ) -> list[GroupConversation]:
        """Get conversations for a group."""
        result = await self._session.execute(
            select(GroupConversationModel)
            .options(selectinload(GroupConversationModel.messages))
            .where(GroupConversationModel.group_id == str(group_id))
            .order_by(GroupConversationModel.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return [GroupConversationMapper.to_entity(model) for model in result.scalars()]

    async def save(self, conversation: GroupConversation) -> GroupConversation:
        """Save a new group conversation."""
        model = GroupConversationMapper.to_model(conversation)
        self._session.add(model)
        
        # Save messages
        for stored_msg in conversation.messages:
            msg_model = GroupMessageMapper.to_model(stored_msg, str(conversation.id))
            self._session.add(msg_model)
        
        await self._session.flush()
        return conversation

    async def update(self, conversation: GroupConversation) -> GroupConversation:
        """Update an existing group conversation."""
        result = await self._session.execute(
            select(GroupConversationModel)
            .options(selectinload(GroupConversationModel.messages))
            .where(GroupConversationModel.id == str(conversation.id))
        )
        model = result.scalar_one_or_none()
        if model:
            GroupConversationMapper.update_model(model, conversation)
            
            # Get existing message IDs
            existing_msg_ids = {msg.id for msg in model.messages}
            
            # Add new messages
            for stored_msg in conversation.messages:
                if str(stored_msg.id) not in existing_msg_ids:
                    msg_model = GroupMessageMapper.to_model(stored_msg, str(conversation.id))
                    self._session.add(msg_model)
            
            await self._session.flush()
        return conversation

    async def delete(self, id: GroupConversationId) -> bool:
        """Delete a group conversation by ID."""
        result = await self._session.execute(
            select(GroupConversationModel).where(GroupConversationModel.id == str(id))
        )
        model = result.scalar_one_or_none()
        if model:
            await self._session.delete(model)
            await self._session.flush()
            return True
        return False

    async def exists(self, id: GroupConversationId) -> bool:
        """Check if a group conversation exists."""
        result = await self._session.execute(
            select(GroupConversationModel.id).where(GroupConversationModel.id == str(id))
        )
        return result.scalar_one_or_none() is not None

    async def search_messages(
        self,
        group_id: GroupId,
        query: str,
        sharing_user_ids: list[UserId] | None = None,
        limit: int = 50,
    ) -> list[GroupConversation]:
        """Search messages in a group, optionally filtering by sharing users for privacy."""
        # Build base query
        stmt = (
            select(GroupConversationModel)
            .options(selectinload(GroupConversationModel.messages))
            .where(GroupConversationModel.group_id == str(group_id))
        )
        
        result = await self._session.execute(stmt.limit(limit))
        conversations = [GroupConversationMapper.to_entity(model) for model in result.scalars()]
        
        # Filter messages by content and optionally by sender
        filtered_conversations = []
        for conv in conversations:
            filtered_messages = []
            for msg in conv.messages:
                # Check if message content matches query
                if query.lower() in msg.message.content.text.lower():
                    # If filtering by sharing users, check sender
                    if sharing_user_ids is None or msg.sender_id in sharing_user_ids:
                        filtered_messages.append(msg)
            
            if filtered_messages:
                # Create a new conversation with only filtered messages
                filtered_conv = conv.model_copy(update={"messages": filtered_messages})
                filtered_conversations.append(filtered_conv)
        
        return filtered_conversations


class SQLAlchemyExtractedEventRepository:
    """SQLAlchemy repository for ExtractedEvent entities."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with database session."""
        self._session = session

    async def get(self, id: EventId) -> ExtractedEvent | None:
        """Get an event by ID."""
        result = await self._session.execute(
            select(ExtractedEventModel).where(ExtractedEventModel.id == str(id))
        )
        model = result.scalar_one_or_none()
        return ExtractedEventMapper.to_entity(model) if model else None

    async def get_by_group(
        self,
        group_id: GroupId,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExtractedEvent]:
        """Get events for a group."""
        result = await self._session.execute(
            select(ExtractedEventModel)
            .where(ExtractedEventModel.group_id == str(group_id))
            .order_by(ExtractedEventModel.event_datetime.asc().nulls_last())
            .offset(offset)
            .limit(limit)
        )
        return [ExtractedEventMapper.to_entity(model) for model in result.scalars()]

    async def get_upcoming(
        self,
        group_id: GroupId,
        limit: int = 20,
    ) -> list[ExtractedEvent]:
        """Get upcoming events for a group."""
        now = datetime.utcnow()
        result = await self._session.execute(
            select(ExtractedEventModel)
            .where(
                and_(
                    ExtractedEventModel.group_id == str(group_id),
                    (ExtractedEventModel.event_datetime >= now) | (ExtractedEventModel.event_datetime.is_(None))
                )
            )
            .order_by(ExtractedEventModel.event_datetime.asc().nulls_last())
            .limit(limit)
        )
        return [ExtractedEventMapper.to_entity(model) for model in result.scalars()]

    async def save(self, event: ExtractedEvent) -> ExtractedEvent:
        """Save a new event."""
        model = ExtractedEventMapper.to_model(event)
        self._session.add(model)
        await self._session.flush()
        return event

    async def update(self, event: ExtractedEvent) -> ExtractedEvent:
        """Update an existing event."""
        result = await self._session.execute(
            select(ExtractedEventModel).where(ExtractedEventModel.id == str(event.id))
        )
        model = result.scalar_one_or_none()
        if model:
            ExtractedEventMapper.update_model(model, event)
            await self._session.flush()
        return event

    async def delete(self, id: EventId) -> bool:
        """Delete an event by ID."""
        result = await self._session.execute(
            select(ExtractedEventModel).where(ExtractedEventModel.id == str(id))
        )
        model = result.scalar_one_or_none()
        if model:
            await self._session.delete(model)
            await self._session.flush()
            return True
        return False

    async def exists(self, id: EventId) -> bool:
        """Check if an event exists."""
        result = await self._session.execute(
            select(ExtractedEventModel.id).where(ExtractedEventModel.id == str(id))
        )
        return result.scalar_one_or_none() is not None
