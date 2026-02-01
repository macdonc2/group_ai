"""Group management API routes."""

import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status

logger = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession

from agent_system.adapters.inbound.api.dependencies import CurrentUserId, SessionDep, get_session
from agent_system.adapters.inbound.api.schemas import (
    ExtractedEventRead,
    ExtractedEventUpdate,
    GroupConversationCreate,
    GroupConversationDetail,
    GroupConversationRead,
    GroupCreate,
    GroupDetail,
    GroupMemberAdd,
    GroupMemberRead,
    GroupMemberUpdate,
    GroupMessageRead,
    GroupRead,
    GroupSummaryRead,
    GroupUpdate,
    SocialSuggestionRead,
)
from agent_system.adapters.outbound.persistence.group_repositories import (
    SQLAlchemyExtractedEventRepository,
    SQLAlchemyGroupConversationRepository,
    SQLAlchemyGroupRepository,
)
from agent_system.adapters.outbound.persistence.repositories import (
    SQLAlchemyConversationRepository,
    SQLAlchemyPlanRepository,
    SQLAlchemyUserRepository,
)
from agent_system.domain.entities import EventType, ExtractedEvent, Group, GroupConversation
from agent_system.domain.value_objects import EventId, GroupConversationId, GroupId, UserId

router = APIRouter(prefix="/groups", tags=["groups"])


async def get_group_repo(session: SessionDep) -> SQLAlchemyGroupRepository:
    """Get group repository."""
    return SQLAlchemyGroupRepository(session)


async def get_group_conv_repo(session: SessionDep) -> SQLAlchemyGroupConversationRepository:
    """Get group conversation repository."""
    return SQLAlchemyGroupConversationRepository(session)


async def require_group_access(
    group_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> Group:
    """Require that the current user is a member of the group."""
    repo = SQLAlchemyGroupRepository(session)
    group = await repo.get(GroupId.from_string(group_id))
    
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found"
        )
    
    if not group.is_member(UserId.from_string(current_user_id)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this group"
        )
    
    return group


async def require_group_owner(
    group_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> Group:
    """Require that the current user is the owner of the group."""
    group = await require_group_access(group_id, current_user_id, session)
    
    if not group.is_owner(UserId.from_string(current_user_id)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the group owner can perform this action"
        )
    
    return group


# ==================== Group CRUD ====================


@router.post("", response_model=GroupRead, status_code=status.HTTP_201_CREATED)
async def create_group(
    data: GroupCreate,
    current_user_id: CurrentUserId,
    session: SessionDep,
):
    """Create a new group with the current user as a member."""
    repo = SQLAlchemyGroupRepository(session)
    user_id = UserId.from_string(current_user_id)
    
    # Group.create() automatically adds the creator as the first member
    group = Group.create(
        name=data.name,
        created_by=user_id,
        description=data.description,
    )
    
    await repo.save(group)
    await session.commit()
    
    return GroupRead(
        id=str(group.id),
        name=group.name,
        description=group.description,
        member_count=group.member_count,
        created_by=str(group.created_by),
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


@router.get("", response_model=list[GroupRead])
async def list_groups(
    current_user_id: CurrentUserId,
    session: SessionDep,
    limit: int = 50,
    offset: int = 0,
):
    """List groups the current user is a member of."""
    repo = SQLAlchemyGroupRepository(session)
    groups = await repo.get_by_user(
        UserId.from_string(current_user_id),
        limit=limit,
        offset=offset,
    )
    
    return [
        GroupRead(
            id=str(g.id),
            name=g.name,
            description=g.description,
            member_count=g.member_count,
            created_by=str(g.created_by),
            created_at=g.created_at,
            updated_at=g.updated_at,
        )
        for g in groups
    ]


@router.get("/{group_id}", response_model=GroupDetail)
async def get_group(
    group_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
):
    """Get group details including members."""
    group = await require_group_access(group_id, current_user_id, session)
    user_repo = SQLAlchemyUserRepository(session)
    
    # Build member list with user emails
    members = []
    for m in group.members:
        user = await user_repo.get(m.user_id)
        members.append(GroupMemberRead(
            id=str(m.id),
            user_id=str(m.user_id),
            user_email=user.email if user else None,
            role=m.role.value,
            sharing_enabled=m.sharing_enabled,
            joined_at=m.joined_at,
            last_seen_at=m.last_seen_at,
        ))
    
    return GroupDetail(
        id=str(group.id),
        name=group.name,
        description=group.description,
        member_count=group.member_count,
        created_by=str(group.created_by),
        created_at=group.created_at,
        updated_at=group.updated_at,
        members=members,
    )


@router.patch("/{group_id}", response_model=GroupRead)
async def update_group(
    group_id: str,
    data: GroupUpdate,
    current_user_id: CurrentUserId,
    session: SessionDep,
):
    """Update group name or description."""
    group = await require_group_access(group_id, current_user_id, session)
    repo = SQLAlchemyGroupRepository(session)
    
    group = group.update_info(
        name=data.name,
        description=data.description,
    )
    
    await repo.update(group)
    await session.commit()
    
    return GroupRead(
        id=str(group.id),
        name=group.name,
        description=group.description,
        member_count=group.member_count,
        created_by=str(group.created_by),
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
):
    """Delete a group (only if you're the only member)."""
    group = await require_group_access(group_id, current_user_id, session)
    repo = SQLAlchemyGroupRepository(session)
    
    if group.member_count > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete group with other members. Remove all members first."
        )
    
    await repo.delete(group.id)
    await session.commit()


# ==================== Group Members ====================


@router.post("/{group_id}/members", response_model=GroupMemberRead, status_code=status.HTTP_201_CREATED)
async def add_member(
    group_id: str,
    data: GroupMemberAdd,
    current_user_id: CurrentUserId,
    session: SessionDep,
):
    """Add a member to the group (only the owner can add members)."""
    group = await require_group_owner(group_id, current_user_id, session)
    repo = SQLAlchemyGroupRepository(session)
    user_repo = SQLAlchemyUserRepository(session)
    
    new_user_id = UserId.from_string(data.user_id)
    
    # Check if user exists
    user = await user_repo.get(new_user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Check if already a member
    if group.is_member(new_user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already a member of this group"
        )
    
    group = group.add_member(new_user_id)
    await repo.update(group)
    await session.commit()
    
    # Get the newly added membership
    membership = group.get_member(new_user_id)
    
    return GroupMemberRead(
        id=str(membership.id),
        user_id=str(membership.user_id),
        user_email=user.email,
        role=membership.role.value,
        sharing_enabled=membership.sharing_enabled,
        joined_at=membership.joined_at,
        last_seen_at=membership.last_seen_at,
    )


@router.delete("/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    group_id: str,
    user_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
):
    """Remove a member from the group (owner can remove anyone, members can only leave)."""
    group = await require_group_access(group_id, current_user_id, session)
    repo = SQLAlchemyGroupRepository(session)
    
    target_user_id = UserId.from_string(user_id)
    current_user = UserId.from_string(current_user_id)
    
    if not group.is_member(target_user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not a member of this group"
        )
    
    # Check permissions: owner can remove anyone, others can only remove themselves
    is_owner = group.is_owner(current_user)
    is_self = target_user_id == current_user
    
    if not is_owner and not is_self:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the group owner can remove other members"
        )
    
    # Prevent owner from removing themselves (would leave group ownerless)
    if is_owner and is_self:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Group owner cannot leave. Transfer ownership or delete the group."
        )
    
    # Prevent removing the last member
    if group.member_count == 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove the last member. Delete the group instead."
        )
    
    group = group.remove_member(target_user_id)
    await repo.update(group)
    await session.commit()


@router.patch("/{group_id}/members/{user_id}", response_model=GroupMemberRead)
async def update_member_settings(
    group_id: str,
    user_id: str,
    data: GroupMemberUpdate,
    current_user_id: CurrentUserId,
    session: SessionDep,
):
    """Update member settings (only self can update own settings)."""
    group = await require_group_access(group_id, current_user_id, session)
    repo = SQLAlchemyGroupRepository(session)
    user_repo = SQLAlchemyUserRepository(session)
    
    # Only allow updating own settings
    if user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own settings"
        )
    
    membership = group.get_member(UserId.from_string(user_id))
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Membership not found"
        )
    
    if data.sharing_enabled is not None:
        membership = membership.toggle_sharing(data.sharing_enabled)
        group = group.update_member(membership)
        await repo.update(group)
        await session.commit()
    
    user = await user_repo.get(membership.user_id)
    
    return GroupMemberRead(
        id=str(membership.id),
        user_id=str(membership.user_id),
        user_email=user.email if user else None,
        role=membership.role.value,
        sharing_enabled=membership.sharing_enabled,
        joined_at=membership.joined_at,
        last_seen_at=membership.last_seen_at,
    )


# ==================== Group Conversations ====================


@router.post("/{group_id}/conversations", response_model=GroupConversationRead, status_code=status.HTTP_201_CREATED)
async def create_group_conversation(
    group_id: str,
    data: GroupConversationCreate,
    current_user_id: CurrentUserId,
    session: SessionDep,
):
    """Create a new conversation in the group."""
    group = await require_group_access(group_id, current_user_id, session)
    repo = SQLAlchemyGroupConversationRepository(session)
    
    conversation = GroupConversation.create(
        group_id=group.id,
        title=data.title,
    )
    
    await repo.save(conversation)
    await session.commit()
    
    return GroupConversationRead(
        id=str(conversation.id),
        group_id=str(conversation.group_id),
        title=conversation.metadata.title,
        message_count=conversation.message_count,
        participant_count=len(conversation.participant_ids),
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


@router.get("/{group_id}/conversations", response_model=list[GroupConversationRead])
async def list_group_conversations(
    group_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
    limit: int = 50,
    offset: int = 0,
):
    """List conversations in a group."""
    group = await require_group_access(group_id, current_user_id, session)
    repo = SQLAlchemyGroupConversationRepository(session)
    
    conversations = await repo.get_by_group(group.id, limit=limit, offset=offset)
    
    return [
        GroupConversationRead(
            id=str(c.id),
            group_id=str(c.group_id),
            title=c.metadata.title,
            message_count=c.message_count,
            participant_count=len(c.participant_ids),
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in conversations
    ]


@router.get("/{group_id}/conversations/{conversation_id}", response_model=GroupConversationDetail)
async def get_group_conversation(
    group_id: str,
    conversation_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
):
    """Get a group conversation with messages."""
    await require_group_access(group_id, current_user_id, session)
    repo = SQLAlchemyGroupConversationRepository(session)
    
    conversation = await repo.get(GroupConversationId.from_string(conversation_id))
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found"
        )
    
    if str(conversation.group_id) != group_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Conversation does not belong to this group"
        )
    
    messages = [
        GroupMessageRead(
            id=str(m.id),
            sender_id=str(m.sender_id),
            role=m.message.role.value,
            content=m.message.content.text,
            timestamp=m.message.timestamp,
            tool_calls=[tc.model_dump() for tc in m.message.tool_calls],
        )
        for m in conversation.messages
    ]
    
    return GroupConversationDetail(
        id=str(conversation.id),
        group_id=str(conversation.group_id),
        title=conversation.metadata.title,
        message_count=conversation.message_count,
        participant_count=len(conversation.participant_ids),
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=messages,
    )


@router.delete("/{group_id}/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group_conversation(
    group_id: str,
    conversation_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
):
    """Delete a group conversation."""
    await require_group_access(group_id, current_user_id, session)
    repo = SQLAlchemyGroupConversationRepository(session)
    
    conversation = await repo.get(GroupConversationId.from_string(conversation_id))
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found"
        )
    
    if str(conversation.group_id) != group_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Conversation does not belong to this group"
        )
    
    await repo.delete(conversation.id)
    await session.commit()


# ==================== Events ====================


@router.get("/{group_id}/events", response_model=list[ExtractedEventRead])
async def list_events(
    group_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
    limit: int = 50,
    offset: int = 0,
):
    """List extracted events for a group, with times in user's timezone."""
    from zoneinfo import ZoneInfo
    
    await require_group_access(group_id, current_user_id, session)
    repo = SQLAlchemyExtractedEventRepository(session)
    user_repo = SQLAlchemyUserRepository(session)
    
    # Get user's timezone
    user = await user_repo.get(UserId.from_string(current_user_id))
    user_tz = user.timezone if user else "UTC"
    
    events = await repo.get_by_group(GroupId.from_string(group_id), limit=limit, offset=offset)
    
    def format_local_datetime(dt: datetime | None, tz_name: str) -> str | None:
        """Convert UTC datetime to user's timezone and format for display."""
        if dt is None:
            return None
        try:
            tz = ZoneInfo(tz_name)
            utc_dt = dt.replace(tzinfo=ZoneInfo("UTC"))
            local_dt = utc_dt.astimezone(tz)
            return local_dt.strftime("%A, %B %d, %Y at %I:%M %p %Z")
        except Exception:
            return dt.isoformat()
    
    def ensure_utc(dt: datetime | None) -> datetime | None:
        """Ensure datetime is UTC-aware for proper JSON serialization."""
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt
    
    return [
        ExtractedEventRead(
            id=str(e.id),
            group_id=str(e.group_id),
            title=e.title,
            description=e.description,
            event_type=e.event_type.value,
            event_datetime=ensure_utc(e.event_datetime),
            event_datetime_local=format_local_datetime(e.event_datetime, user_tz),
            timezone=user_tz,
            location=e.location,
            participant_ids=[str(p) for p in e.participant_ids],
            confidence=e.confidence,
            is_confirmed=e.is_confirmed,
            created_at=e.created_at,
            google_event_id=e.google_event_id,
            google_sync_status=e.google_sync_status.value,
        )
        for e in events
    ]


@router.get("/{group_id}/events/upcoming", response_model=list[ExtractedEventRead])
async def list_upcoming_events(
    group_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
    limit: int = 20,
):
    """List upcoming events for a group, with times in user's timezone."""
    from zoneinfo import ZoneInfo
    
    await require_group_access(group_id, current_user_id, session)
    repo = SQLAlchemyExtractedEventRepository(session)
    user_repo = SQLAlchemyUserRepository(session)
    
    # Get user's timezone
    user = await user_repo.get(UserId.from_string(current_user_id))
    user_tz = user.timezone if user else "UTC"
    
    events = await repo.get_upcoming(GroupId.from_string(group_id), limit=limit)
    
    def format_local_datetime(dt: datetime | None, tz_name: str) -> str | None:
        """Convert UTC datetime to user's timezone and format for display."""
        if dt is None:
            return None
        try:
            tz = ZoneInfo(tz_name)
            # Assume stored datetime is UTC (naive), make it aware
            utc_dt = dt.replace(tzinfo=ZoneInfo("UTC"))
            local_dt = utc_dt.astimezone(tz)
            return local_dt.strftime("%A, %B %d, %Y at %I:%M %p %Z")
        except Exception:
            return dt.isoformat()
    
    def ensure_utc(dt: datetime | None) -> datetime | None:
        """Ensure datetime is UTC-aware for proper JSON serialization."""
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt
    
    return [
        ExtractedEventRead(
            id=str(e.id),
            group_id=str(e.group_id),
            title=e.title,
            description=e.description,
            event_type=e.event_type.value,
            event_datetime=ensure_utc(e.event_datetime),
            event_datetime_local=format_local_datetime(e.event_datetime, user_tz),
            timezone=user_tz,
            location=e.location,
            participant_ids=[str(p) for p in e.participant_ids],
            confidence=e.confidence,
            is_confirmed=e.is_confirmed,
            created_at=e.created_at,
            google_event_id=e.google_event_id,
            google_sync_status=e.google_sync_status.value,
        )
        for e in events
    ]


@router.patch("/{group_id}/events/{event_id}", response_model=ExtractedEventRead)
async def update_event(
    group_id: str,
    event_id: str,
    data: ExtractedEventUpdate,
    current_user_id: CurrentUserId,
    session: SessionDep,
):
    """Update an extracted event (confirm, edit details)."""
    await require_group_access(group_id, current_user_id, session)
    repo = SQLAlchemyExtractedEventRepository(session)
    
    event = await repo.get(EventId.from_string(event_id))
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )
    
    if str(event.group_id) != group_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Event does not belong to this group"
        )
    
    # Update event fields
    event = event.update(
        title=data.title,
        description=data.description,
        event_datetime=data.event_datetime,
        location=data.location,
    )
    
    was_just_confirmed = False
    if data.is_confirmed is not None:
        if data.is_confirmed and not event.is_confirmed:
            event = event.confirm()
            was_just_confirmed = True
        elif not data.is_confirmed:
            event = event.model_copy(update={"is_confirmed": False})
    
    # Auto-sync to Google Calendar for ALL group members with calendar connected
    if was_just_confirmed:
        try:
            from agent_system.adapters.outbound.persistence import SQLAlchemyUserRepository
            from agent_system.application.services import CalendarSyncService
            from agent_system.composition_root.container import get_container
            from agent_system.domain.value_objects import UserId
            
            container = await get_container()
            if container.google_calendar_adapter:
                user_repo = SQLAlchemyUserRepository(session)
                group_repo = SQLAlchemyGroupRepository(session)
                group = await group_repo.get(GroupId.from_string(group_id))
                
                if group:
                    sync_service = CalendarSyncService(container.google_calendar_adapter)
                    synced_count = 0
                    
                    # Sync to all group members who have calendar enabled
                    for member in group.members:
                        try:
                            member_user = await user_repo.get(member.user_id)
                            if (member_user and 
                                member_user.has_google_calendar_connected() and 
                                member_user.preferences.google_calendar_enabled):
                                # Sync this event to the member's calendar
                                event = await sync_service.sync_event_to_google(event, member_user)
                                synced_count += 1
                                logger.info(f"Synced event {event.id} to {member_user.email}'s calendar")
                        except Exception as member_e:
                            logger.warning(f"Failed to sync event to member {member.user_id}: {member_e}")
                    
                    if synced_count > 0:
                        logger.info(f"Auto-synced confirmed event {event.id} to {synced_count} member calendars")
        except Exception as e:
            logger.error(f"Failed to auto-sync event to Google Calendar: {e}")
            # Don't fail the request if sync fails
    
    await repo.update(event)
    await session.commit()
    
    return ExtractedEventRead(
        id=str(event.id),
        group_id=str(event.group_id),
        title=event.title,
        description=event.description,
        event_type=event.event_type.value,
        event_datetime=event.event_datetime,
        location=event.location,
        participant_ids=[str(p) for p in event.participant_ids],
        confidence=event.confidence,
        is_confirmed=event.is_confirmed,
        created_at=event.created_at,
        google_event_id=event.google_event_id,
        google_sync_status=event.google_sync_status.value,
    )


@router.post("/{group_id}/events/{event_id}/sync", response_model=ExtractedEventRead)
async def sync_event_to_calendar(
    group_id: str,
    event_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
):
    """Manually sync an event to the current user's Google Calendar."""
    from agent_system.adapters.outbound.persistence import SQLAlchemyUserRepository
    from agent_system.application.services import CalendarSyncService
    from agent_system.composition_root.container import get_container
    from agent_system.domain.value_objects import UserId
    
    await require_group_access(group_id, current_user_id, session)
    repo = SQLAlchemyExtractedEventRepository(session)
    
    event = await repo.get(EventId.from_string(event_id))
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )
    
    if str(event.group_id) != group_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Event does not belong to this group"
        )
    
    if not event.is_confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only confirmed events can be synced to calendar"
        )
    
    if not event.event_datetime:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event has no date/time set. Please edit the event to add a specific date and time before syncing."
        )
    
    # Get user and check calendar connection
    user_repo = SQLAlchemyUserRepository(session)
    user = await user_repo.get(UserId.from_string(current_user_id))
    
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    if not user.has_google_calendar_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Calendar is not connected. Please connect your calendar in Settings."
        )
    
    if not user.preferences.google_calendar_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Calendar sync is not enabled. Enable it in Settings."
        )
    
    # Sync to calendar
    container = await get_container()
    if not container.google_calendar_adapter:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Calendar service is not available"
        )
    
    sync_service = CalendarSyncService(container.google_calendar_adapter)
    event = await sync_service.sync_event_to_google(event, user)
    
    await repo.update(event)
    await session.commit()
    
    logger.info(f"Manually synced event {event.id} to Google Calendar for user {current_user_id}")
    
    return ExtractedEventRead(
        id=str(event.id),
        group_id=str(event.group_id),
        title=event.title,
        description=event.description,
        event_type=event.event_type.value,
        event_datetime=event.event_datetime,
        location=event.location,
        participant_ids=[str(p) for p in event.participant_ids],
        confidence=event.confidence,
        is_confirmed=event.is_confirmed,
        created_at=event.created_at,
        google_event_id=event.google_event_id,
        google_sync_status=event.google_sync_status.value,
    )


@router.delete("/{group_id}/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    group_id: str,
    event_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
):
    """Delete an extracted event (dismiss false positive)."""
    await require_group_access(group_id, current_user_id, session)
    repo = SQLAlchemyExtractedEventRepository(session)
    
    event = await repo.get(EventId.from_string(event_id))
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )
    
    if str(event.group_id) != group_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Event does not belong to this group"
        )
    
    await repo.delete(event.id)
    await session.commit()


# ==================== Summary and Social ====================


@router.get("/{group_id}/summary", response_model=GroupSummaryRead)
async def get_group_summary(
    group_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
):
    """Get a summary of recent group activity with themes.
    
    Note: Only messages from members with sharing_enabled=True are included
    in the summary to respect privacy preferences.
    """
    group = await require_group_access(group_id, current_user_id, session)
    group_repo = SQLAlchemyGroupRepository(session)
    conv_repo = SQLAlchemyGroupConversationRepository(session)
    event_repo = SQLAlchemyExtractedEventRepository(session)
    
    # Get IDs of members who have opted in to sharing
    sharing_member_ids = await group_repo.get_sharing_member_ids(group.id)
    sharing_member_id_set = set(sharing_member_ids)
    
    # Get recent conversations
    conversations = await conv_repo.get_by_group(group.id, limit=10)
    
    # Build message text for summarization (only from sharing members)
    messages_text = ""
    message_count = 0
    for conv in conversations:
        for msg in conv.messages[-20:]:  # Last 20 messages per conversation
            # Only include messages from members who have sharing enabled
            if msg.sender_id in sharing_member_id_set:
                messages_text += f"[{msg.sender_id}]: {msg.message.content.text}\n"
                message_count += 1
    
    # Get upcoming events
    upcoming_events = await event_repo.get_upcoming(group.id, limit=10)
    
    if not messages_text.strip():
        # No messages to summarize
        return GroupSummaryRead(
            themes=[],
            upcoming_events=[
                ExtractedEventRead(
                    id=str(e.id),
                    group_id=str(e.group_id),
                    title=e.title,
                    description=e.description,
                    event_type=e.event_type.value,
                    event_datetime=e.event_datetime,
                    location=e.location,
                    participant_ids=[str(p) for p in e.participant_ids],
                    confidence=e.confidence,
                    is_confirmed=e.is_confirmed,
                    created_at=e.created_at,
                    google_event_id=e.google_event_id,
                    google_sync_status=e.google_sync_status.value,
                )
                for e in upcoming_events
            ],
            social_suggestions=[],
            active_member_ids=[str(m.user_id) for m in group.members],
            message_count_week=message_count,
        )
    
    # Generate summary using LLM
    from agent_system.adapters.outbound.llm import generate_group_summary
    
    try:
        summary_result = await generate_group_summary(messages_text)
        themes = summary_result.themes[:5]
    except Exception as e:
        logger.warning(f"Group summary generation failed: {e}")
        themes = []
    
    return GroupSummaryRead(
        themes=[t.theme for t in themes],
        upcoming_events=[
            ExtractedEventRead(
                id=str(e.id),
                group_id=str(e.group_id),
                title=e.title,
                description=e.description,
                event_type=e.event_type.value,
                event_datetime=e.event_datetime,
                location=e.location,
                participant_ids=[str(p) for p in e.participant_ids],
                confidence=e.confidence,
                is_confirmed=e.is_confirmed,
                created_at=e.created_at,
                google_event_id=e.google_event_id,
                google_sync_status=e.google_sync_status.value,
            )
            for e in upcoming_events
        ],
        social_suggestions=[],
        active_member_ids=[str(m.user_id) for m in group.members],
        message_count_week=message_count,
    )


@router.get("/{group_id}/social/suggestions", response_model=list[SocialSuggestionRead])
async def get_social_suggestions(
    group_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
):
    """Get social activity suggestions for the group based on interests and events.
    
    Note: Only data from members with sharing_enabled=True is used for suggestions
    to respect privacy preferences.
    """
    group = await require_group_access(group_id, current_user_id, session)
    group_repo = SQLAlchemyGroupRepository(session)
    conv_repo = SQLAlchemyGroupConversationRepository(session)
    event_repo = SQLAlchemyExtractedEventRepository(session)
    user_repo = SQLAlchemyUserRepository(session)
    
    # Get IDs of members who have opted in to sharing
    sharing_member_ids = await group_repo.get_sharing_member_ids(group.id)
    sharing_member_id_set = set(sharing_member_ids)
    
    # Build context for social matching (only from sharing members)
    context_parts = ["GROUP MEMBERS (who have opted in to sharing):"]
    for membership in group.members:
        # Only include members who have sharing enabled
        if not membership.sharing_enabled:
            continue
        user = await user_repo.get(membership.user_id)
        if user:
            patterns = [p.description for p in user.learned_patterns[:5]]
            context_parts.append(f"- {user.email}: {', '.join(patterns) if patterns else 'No known interests'}")
    
    context_parts.append("\nRECENT CONVERSATIONS (from sharing members):")
    conversations = await conv_repo.get_by_group(group.id, limit=5)
    for conv in conversations:
        for msg in conv.messages[-10:]:
            # Only include messages from members who have sharing enabled
            if msg.sender_id in sharing_member_id_set:
                context_parts.append(f"  [{msg.sender_id}]: {msg.message.content.text[:200]}")
    
    context_parts.append("\nUPCOMING EVENTS:")
    events = await event_repo.get_upcoming(group.id, limit=5)
    for event in events:
        context_parts.append(f"  - {event.title}: {event.description or 'No description'}")
    
    context_text = "\n".join(context_parts)
    
    if len(context_text) < 100:
        # Not enough context
        return []
    
    # Generate social suggestions using LLM
    from agent_system.adapters.outbound.llm import generate_social_suggestions
    
    try:
        result = await generate_social_suggestions(context_text)
        return [
            SocialSuggestionRead(
                title=s.title,
                description=s.description,
                suggested_participants=s.suggested_participants,
                reason=s.reason,
                event_type=s.activity_type,
            )
            for s in result.suggestions[:5]
        ]
    except Exception as e:
        logger.warning(f"Social suggestions generation failed: {e}")
        return []


# ==================== WebSocket Real-Time Chat ====================

logger = logging.getLogger(__name__)


@router.websocket("/{group_id}/conversations/{conversation_id}/ws")
async def websocket_chat(
    websocket: WebSocket,
    group_id: str,
    conversation_id: str,
    user_id: str = Query(..., description="User ID for authentication"),
):
    """WebSocket endpoint for real-time group chat.
    
    Message types from client:
    - {"type": "message", "data": {"content": "..."}}
    - {"type": "typing", "data": {}}
    - {"type": "stop_typing", "data": {}}
    
    Message types from server:
    - {"type": "new_message", "data": {...}}
    - {"type": "user_joined", "data": {...}}
    - {"type": "user_left", "data": {...}}
    - {"type": "typing_update", "data": {"typing_users": [...]}}
    - {"type": "event_extracted", "data": {...}}
    - {"type": "agent_thinking", "data": {...}}
    - {"type": "error", "data": {"message": "..."}}
    """
    from agent_system.adapters.inbound.api.websocket import (
        WebSocketMessage,
        WebSocketMessageType,
        connection_manager,
    )
    from agent_system.adapters.outbound.persistence import Database
    from agent_system.adapters.inbound.api.dependencies import _database
    from agent_system.domain.value_objects import Message as DomainMessage
    
    # Verify access before accepting connection
    if _database is None:
        await websocket.close(code=1011, reason="Database not initialized")
        return
    
    async with _database.session() as session:
        group_repo = SQLAlchemyGroupRepository(session)
        conv_repo = SQLAlchemyGroupConversationRepository(session)
        user_repo = SQLAlchemyUserRepository(session)
        
        # Verify group membership
        group = await group_repo.get(GroupId.from_string(group_id))
        if not group:
            await websocket.close(code=4004, reason="Group not found")
            return
        
        if not group.is_member(UserId.from_string(user_id)):
            await websocket.close(code=4003, reason="Not a member of this group")
            return
        
        # Verify conversation exists
        conversation = await conv_repo.get(GroupConversationId.from_string(conversation_id))
        if not conversation:
            await websocket.close(code=4004, reason="Conversation not found")
            return
        
        if str(conversation.group_id) != group_id:
            await websocket.close(code=4003, reason="Conversation not in this group")
            return
        
        # Get user info
        user = await user_repo.get(UserId.from_string(user_id))
        user_info = user.email if user else user_id
    
    # Connect to the WebSocket
    await connection_manager.connect(
        websocket,
        group_id,
        conversation_id,
        user_id,
        user_info,
    )
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
                msg_type = message.get("type")
                msg_data = message.get("data", {})
                
                if msg_type == "message":
                    # Handle new chat message
                    content = msg_data.get("content", "").strip()
                    if not content:
                        continue
                    
                    msg_id = ""
                    should_invoke_agent = "@agent" in content.lower() or "@assistant" in content.lower()
                    
                    # Save message to database
                    async with _database.session() as session:
                        conv_repo = SQLAlchemyGroupConversationRepository(session)
                        conversation = await conv_repo.get(
                            GroupConversationId.from_string(conversation_id)
                        )
                        
                        if conversation:
                            # Create and add message
                            domain_message = DomainMessage.user(content)
                            conversation = conversation.add_message(
                                domain_message,
                                UserId.from_string(user_id),
                            )
                            await conv_repo.update(conversation)
                            await session.commit()
                            logger.info(f"=== Message saved: {content[:30]}... ===")
                            
                            # Get the message ID
                            last_msg = conversation.last_message
                            msg_id = str(last_msg.id) if last_msg else ""
                            
                            # Broadcast to all users in conversation
                            await connection_manager.broadcast_new_message(
                                group_id,
                                conversation_id,
                                msg_id,
                                user_id,
                                content,
                                "user",
                            )
                            
                            # Store user message embedding in background (fire-and-forget)
                            # This runs asynchronously to avoid blocking the WebSocket handler
                            async def store_user_message_embedding():
                                try:
                                    import asyncio
                                    from agent_system.composition_root.container import get_container
                                    from agent_system.adapters.outbound.embedding import OpenAIEmbeddingAdapter
                                    from agent_system.domain.utils.encryption import get_api_key_encryption
                                    
                                    # Timeout after 10 seconds to prevent hangs
                                    async with asyncio.timeout(10):
                                        container = await get_container()
                                        
                                        # Need knowledge graph for storage
                                        if not container.knowledge_graph_adapter:
                                            logger.debug("No knowledge graph adapter - skipping embedding storage")
                                            return
                                        
                                        # Get user's API key for embedding
                                        api_key_for_embedding: str | None = None
                                        user_email = "Unknown"
                                        async with _database.session() as embed_session:
                                            user_for_embed = await SQLAlchemyUserRepository(embed_session).get(UserId.from_string(user_id))
                                            if user_for_embed:
                                                user_email = user_for_embed.email
                                                if user_for_embed.has_api_key():
                                                    try:
                                                        encryption = get_api_key_encryption()
                                                        api_key_for_embedding = encryption.decrypt(user_for_embed.encrypted_openai_api_key)
                                                    except Exception:
                                                        pass
                                        
                                        # Fall back to system key
                                        if not api_key_for_embedding:
                                            from agent_system.composition_root.config import get_settings
                                            api_key_for_embedding = get_settings().openai_api_key
                                        
                                        if not api_key_for_embedding:
                                            logger.debug("No API key available for embeddings")
                                            return
                                        
                                        # Create embedding adapter with user's key
                                        embedding_adapter = OpenAIEmbeddingAdapter(api_key=api_key_for_embedding)
                                        user_embedding = await embedding_adapter.embed(content)
                                        
                                        await container.knowledge_graph_adapter.store_group_message_embedding(
                                            group_id=group_id,
                                            conversation_id=conversation_id,
                                            message_id=msg_id,
                                            user_id=user_id,
                                            user_email=user_email,
                                            content=content,
                                            role="user",
                                            embedding=user_embedding.embedding,
                                            metadata={},
                                        )
                                        logger.info(f"Stored user message embedding: {msg_id}")
                                except asyncio.TimeoutError:
                                    logger.warning("User message embedding storage timed out")
                                except Exception as embed_err:
                                    logger.debug(f"Failed to store user message embedding: {embed_err}")
                            
                            # Fire and forget - don't await, let it run in background
                            import asyncio
                            asyncio.create_task(store_user_message_embedding())
                    
                    logger.info(f"=== After database session, should_invoke_agent={should_invoke_agent} ===")
                    
                    # Invoke agent if mentioned
                    if should_invoke_agent:
                        try:
                            # Broadcast that agent is thinking
                            await connection_manager.broadcast_agent_status(
                                group_id,
                                conversation_id,
                                "thinking",
                                "Processing your request...",
                            )
                            
                            # Strip @agent mention from the query
                            import re
                            agent_query = re.sub(r'@(agent|assistant)\b', '', content, flags=re.IGNORECASE).strip()
                            
                            # Set up agent workflow with proper state and dependencies
                            from agent_system.adapters.outbound.fsm import (
                                AgentDependencies,
                                WorkflowState,
                                run_agent_workflow,
                            )
                            from agent_system.composition_root.config import get_settings
                            from agent_system.domain.entities import Conversation as DomainConversation, User
                            
                            settings = get_settings()
                            
                            async with _database.session() as session:
                                user_repo = SQLAlchemyUserRepository(session)
                                conv_repo = SQLAlchemyConversationRepository(session)
                                plan_repo = SQLAlchemyPlanRepository(session)
                                group_conv_repo = SQLAlchemyGroupConversationRepository(session)
                                
                                # Get user
                                user = await user_repo.get(UserId.from_string(user_id))
                                if not user:
                                    # Create user if doesn't exist
                                    user = User.create(
                                        email=f"user_{user_id[:8]}@example.com",
                                        hashed_password="temp",
                                    )
                                    user = user.model_copy(update={"id": UserId.from_string(user_id)})
                                    await user_repo.save(user)
                                    await session.commit()
                                
                                # Get API key - try user's personal key first, then system key
                                import os
                                agent_api_key: str | None = None
                                
                                if user.has_api_key():
                                    try:
                                        from agent_system.domain.utils.encryption import get_api_key_encryption
                                        encryption = get_api_key_encryption()
                                        agent_api_key = encryption.decrypt(user.encrypted_openai_api_key)
                                        logger.info(f"Using user's personal API key for group agent")
                                    except Exception as key_err:
                                        logger.warning(f"Failed to decrypt user API key: {key_err}")
                                
                                if not agent_api_key and settings.openai_api_key:
                                    agent_api_key = settings.openai_api_key
                                    logger.info(f"Using system API key for group agent")
                                
                                if not agent_api_key:
                                    logger.error("No API key available for group agent")
                                    await connection_manager.broadcast_agent_status(
                                        group_id, conversation_id, "error",
                                        "No API key configured. Please add your OpenAI API key in Settings."
                                    )
                                    continue
                                
                                # Set environment variable for PydanticAI
                                os.environ["OPENAI_API_KEY"] = agent_api_key
                                
                                # Get group conversation for context
                                group_conversation = await group_conv_repo.get(
                                    GroupConversationId.from_string(conversation_id)
                                )
                                
                                # Build conversation history from group chat
                                history_messages = []
                                if group_conversation:
                                    for stored_msg in group_conversation.messages[-10:]:
                                        history_messages.append(stored_msg.message)
                                
                                # Create a temporary conversation with the history
                                temp_conversation = DomainConversation.create(user_id=user.id)
                                for msg in history_messages:
                                    temp_conversation = temp_conversation.add_message(msg)
                                
                                # Create workflow state
                                state = WorkflowState(
                                    user=user,
                                    conversation=temp_conversation,
                                    current_plan=None,
                                )
                                
                                # Get knowledge graph from container
                                from agent_system.composition_root.container import get_container
                                container = await get_container()
                                
                                # Generate message ID for streaming chunks
                                pending_agent_msg_id = str(uuid.uuid4())
                                
                                # Create event callback for streaming chunks
                                async def streaming_event_callback(
                                    event_type: str,
                                    node_name: str,
                                    data: str,
                                    metadata: dict | None = None,
                                ) -> None:
                                    """Handle events from the workflow, including streaming chunks."""
                                    if event_type == "response_chunk":
                                        # Broadcast streaming chunk to all connected clients
                                        await connection_manager.broadcast_agent_chunk(
                                            group_id,
                                            conversation_id,
                                            pending_agent_msg_id,
                                            data,  # The chunk text
                                            is_complete=False,
                                        )
                                    elif event_type == "node_start" and node_name == "GenerateResponse":
                                        # Update agent status to show response is being generated
                                        await connection_manager.broadcast_agent_status(
                                            group_id,
                                            conversation_id,
                                            "generating",
                                            node_name,
                                        )
                                
                                # Create dependencies with group context and streaming callback
                                deps = AgentDependencies(
                                    llm_port=None,
                                    user_repository=user_repo,
                                    conversation_repository=conv_repo,
                                    plan_repository=plan_repo,
                                    knowledge_graph_port=container.knowledge_graph_adapter,
                                    embedding_port=container.embedding_adapter,
                                    openai_api_key=agent_api_key,
                                    default_model=settings.default_model,
                                    event_callback=streaming_event_callback,
                                )
                                
                                # Add group context to state for tools
                                state.group_context = {
                                    "group_id": group_id,
                                    "conversation_id": conversation_id,
                                }
                                
                                # Run the agent workflow
                                result = await run_agent_workflow(
                                    user_input=agent_query,
                                    state=state,
                                    deps=deps,
                                )
                            
                            agent_response = result.response
                            agent_msg_id = pending_agent_msg_id  # Use the same ID used for streaming
                            
                            # Broadcast streaming completion signal
                            await connection_manager.broadcast_agent_chunk(
                                group_id,
                                conversation_id,
                                agent_msg_id,
                                "",  # Empty chunk
                                is_complete=True,
                            )
                            
                            # Save agent response to conversation
                            try:
                                async with _database.session() as session:
                                    conv_repo = SQLAlchemyGroupConversationRepository(session)
                                    conversation = await conv_repo.get(
                                        GroupConversationId.from_string(conversation_id)
                                    )
                                    
                                    if conversation:
                                        assistant_message = DomainMessage.assistant(agent_response)
                                        # Use a special "assistant" user ID
                                        assistant_user_id = UserId.from_string("00000000-0000-0000-0000-000000000000")
                                        conversation = conversation.add_message(
                                            assistant_message,
                                            assistant_user_id,
                                        )
                                        await conv_repo.update(conversation)
                                        await session.commit()
                                        
                                        last_msg = conversation.last_message
                                        # Update agent_msg_id to the actual saved message ID
                                        agent_msg_id = str(last_msg.id) if last_msg else agent_msg_id
                                        logger.info(f"Saved agent response to conversation {conversation_id}, msg_id: {agent_msg_id}")
                                    else:
                                        logger.warning(f"Conversation {conversation_id} not found when saving agent response")
                            except Exception as save_error:
                                logger.error(f"Failed to save agent response to database: {save_error}")
                            
                            # ALWAYS broadcast agent response to frontend, even if DB save failed
                            # This ensures clients that missed chunks or joined late get the full message
                            logger.info(f"Broadcasting agent response to group {group_id}, conversation {conversation_id}")
                            await connection_manager.broadcast_new_message(
                                group_id,
                                conversation_id,
                                agent_msg_id,
                                "00000000-0000-0000-0000-000000000000",
                                agent_response,
                                "assistant",
                            )
                            logger.info(f"Agent response broadcast complete")
                            
                            # Store agent response embedding (secondary, non-critical)
                            try:
                                if container.knowledge_graph_adapter:
                                    # Use user's API key for embeddings
                                    from agent_system.adapters.outbound.embedding import OpenAIEmbeddingAdapter
                                    embed_api_key = settings.openai_api_key
                                    if not embed_api_key and user and user.has_api_key():
                                        try:
                                            from agent_system.domain.utils.encryption import get_api_key_encryption
                                            embed_api_key = get_api_key_encryption().decrypt(user.encrypted_openai_api_key)
                                        except Exception:
                                            pass
                                    
                                    if embed_api_key:
                                        embed_adapter = OpenAIEmbeddingAdapter(api_key=embed_api_key)
                                        agent_embedding = await embed_adapter.embed(agent_response)
                                        await container.knowledge_graph_adapter.store_group_message_embedding(
                                            group_id=group_id,
                                            conversation_id=conversation_id,
                                            message_id=agent_msg_id,
                                            user_id="00000000-0000-0000-0000-000000000000",
                                            user_email="Assistant",
                                            content=agent_response,
                                            role="assistant",
                                            embedding=agent_embedding.embedding,
                                            metadata={"tools_used": result.tools_used},
                                        )
                                        logger.info(f"Stored agent response embedding: {agent_msg_id}")
                            except Exception as embed_error:
                                logger.debug(f"Failed to store agent embedding: {embed_error}")
                            
                            # Clear thinking status
                            await connection_manager.broadcast_agent_status(
                                group_id,
                                conversation_id,
                                "idle",
                                None,
                            )
                            
                        except Exception as e:
                            logger.error(f"Agent invocation failed: {e}")
                            await connection_manager.broadcast_agent_status(
                                group_id,
                                conversation_id,
                                "error",
                                f"Agent error: {str(e)[:100]}",
                            )
                    
                    # Extract events from the message asynchronously
                    logger.info(f"=== Starting event extraction for message: {content[:50]}... ===")
                    try:
                        from agent_system.adapters.outbound.llm import extract_events_from_text
                        from agent_system.composition_root.config import get_settings
                        
                        # Get API key for event extraction
                        api_key_for_extraction: str | None = None
                        async with _database.session() as session:
                            user_for_key = await SQLAlchemyUserRepository(session).get(UserId.from_string(user_id))
                            if user_for_key and user_for_key.has_api_key():
                                try:
                                    from agent_system.domain.utils.encryption import get_api_key_encryption
                                    encryption = get_api_key_encryption()
                                    api_key_for_extraction = encryption.decrypt(user_for_key.encrypted_openai_api_key)
                                except Exception as decrypt_err:
                                    logger.warning(f"Failed to decrypt user API key for events: {decrypt_err}")
                        
                        # Fall back to system key if user key not available
                        if not api_key_for_extraction:
                            settings = get_settings()
                            api_key_for_extraction = settings.openai_api_key
                        
                        if not api_key_for_extraction:
                            logger.warning("No API key available for event extraction, skipping")
                        else:
                            # Fetch recent conversation context for better event extraction
                            # This allows the extractor to match "We're going to the Queen Legacy show" 
                            # with the full event details from a recent agent response
                            recent_context: list[dict[str, str]] = []
                            try:
                                async with _database.session() as context_session:
                                    context_conv_repo = SQLAlchemyGroupConversationRepository(context_session)
                                    context_conv = await context_conv_repo.get(
                                        GroupConversationId.from_string(conversation_id)
                                    )
                                    if context_conv and context_conv.messages:
                                        # Get last 10 messages (excluding the current one we just added)
                                        # StoredGroupMessage has .message.role and .message.content.text
                                        recent_msgs = list(context_conv.messages)[-11:-1] if len(context_conv.messages) > 1 else []
                                        for stored_msg in recent_msgs:
                                            # Access the inner Message object
                                            inner_msg = stored_msg.message
                                            role_str = inner_msg.role.value if hasattr(inner_msg.role, 'value') else str(inner_msg.role)
                                            content_str = inner_msg.content.text if hasattr(inner_msg.content, 'text') else str(inner_msg.content)
                                            recent_context.append({
                                                "role": role_str,
                                                "content": content_str,
                                            })
                                        logger.info(f"Loaded {len(recent_context)} messages as context for event extraction")
                            except Exception as ctx_err:
                                logger.warning(f"Could not load conversation context: {ctx_err}")
                            
                            logger.info(f"Extracting events from: {content[:100]}")
                            result = await extract_events_from_text(
                                content, 
                                api_key=api_key_for_extraction,
                                context=recent_context if recent_context else None,
                            )
                            logger.info(f"Event extraction result: {len(result.events)} events, reasoning: {result.reasoning}")
                            
                            if result.events:
                                async with _database.session() as session:
                                    event_repo = SQLAlchemyExtractedEventRepository(session)
                                    
                                    # Get the user's timezone for proper datetime parsing
                                    from zoneinfo import ZoneInfo
                                    user_tz_name = "UTC"
                                    try:
                                        user_repo = SQLAlchemyUserRepository(session)
                                        user_for_tz = await user_repo.get(UserId.from_string(user_id))
                                        if user_for_tz and user_for_tz.timezone:
                                            user_tz_name = user_for_tz.timezone
                                            logger.info(f"Using user timezone for event parsing: {user_tz_name}")
                                    except Exception as tz_err:
                                        logger.warning(f"Could not get user timezone: {tz_err}")
                                    
                                    for extracted in result.events:
                                        logger.info(f"Extracted event: {extracted.title}, confidence: {extracted.confidence}")
                                        if extracted.confidence >= 0.7:
                                            # Try to parse the datetime string with smart vague reference handling
                                            event_datetime = None
                                            if extracted.datetime_str:
                                                try:
                                                    from agent_system.application.services import parse_vague_datetime
                                                    
                                                    # Use smart datetime parser with LLM fallback for vague references
                                                    # "tonight" -> 6 PM, "tomorrow" -> 9 AM, "next week" -> 7 days at 9 AM
                                                    event_datetime = await parse_vague_datetime(
                                                        extracted.datetime_str,
                                                        user_timezone=user_tz_name,
                                                        api_key=api_key_for_extraction,
                                                    )
                                                    
                                                    if event_datetime:
                                                        logger.info(f"Parsed datetime (user tz {user_tz_name}): {extracted.datetime_str} -> UTC: {event_datetime}")
                                                    else:
                                                        logger.warning(f"Could not parse datetime: '{extracted.datetime_str}'")
                                                except Exception as parse_err:
                                                    logger.warning(f"Could not parse datetime '{extracted.datetime_str}': {parse_err}")
                                            
                                            # Create domain event
                                            event = ExtractedEvent.create(
                                                group_id=GroupId.from_string(group_id),
                                                title=extracted.title,
                                                event_type=EventType(extracted.event_type),
                                                description=extracted.description or extracted.datetime_str,  # Use datetime as description fallback
                                                event_datetime=event_datetime,
                                                location=extracted.location,
                                                confidence=extracted.confidence,
                                            )
                                            
                                            await event_repo.save(event)
                                            await session.commit()
                                            logger.info(f"Saved event: {event.title} (id: {event.id})")
                                            
                                            # Format local datetime for display
                                            event_datetime_local = None
                                            if event_datetime:
                                                try:
                                                    from datetime import timezone as dt_tz
                                                    utc_dt = event_datetime.replace(tzinfo=dt_tz.utc)
                                                    local_dt = utc_dt.astimezone(user_tz)
                                                    event_datetime_local = local_dt.strftime("%A, %B %d, %Y at %I:%M %p %Z")
                                                except Exception:
                                                    event_datetime_local = event_datetime.isoformat()
                                            
                                            # Broadcast event extraction
                                            await connection_manager.broadcast_event_extracted(
                                                group_id,
                                                conversation_id,
                                                {
                                                    "id": str(event.id),
                                                    "title": event.title,
                                                    "description": event.description,
                                                    "event_type": event.event_type.value,
                                                    "event_datetime": event_datetime.isoformat() if event_datetime else extracted.datetime_str,
                                                    "event_datetime_local": event_datetime_local,
                                                    "timezone": user_tz_name,
                                                    "location": event.location,
                                                    "confidence": event.confidence,
                                                    "group_id": group_id,
                                                },
                                            )
                                            logger.info(f"Broadcasted event: {event.title}")
                                        else:
                                            logger.info(f"Skipped event '{extracted.title}' - confidence too low: {extracted.confidence}")
                            else:
                                logger.info("No events detected in message")
                    except Exception as e:
                        logger.error(f"Event extraction failed: {e}", exc_info=True)
                    
                    # Extract knowledge entities (people, pets, locations, preferences) asynchronously
                    # This runs in parallel with regular message processing
                    try:
                        from agent_system.adapters.outbound.llm.knowledge_extractor import extract_knowledge_from_text
                        from agent_system.composition_root.config import get_settings
                        
                        # Get API key for entity extraction (reuse logic from event extraction)
                        api_key_for_entities: str | None = None
                        async with _database.session() as session:
                            user_for_key = await SQLAlchemyUserRepository(session).get(UserId.from_string(user_id))
                            if user_for_key and user_for_key.has_api_key():
                                try:
                                    from agent_system.domain.utils.encryption import get_api_key_encryption
                                    encryption = get_api_key_encryption()
                                    api_key_for_entities = encryption.decrypt(user_for_key.encrypted_openai_api_key)
                                except Exception as decrypt_err:
                                    logger.debug(f"Failed to decrypt user API key for entities: {decrypt_err}")
                        
                        # Fall back to system key
                        if not api_key_for_entities:
                            settings = get_settings()
                            api_key_for_entities = settings.openai_api_key
                        
                        if api_key_for_entities and _neo4j_adapter:
                            # Get existing entities for reference resolution
                            existing_persons: list[str] = []
                            existing_pets: list[str] = []
                            existing_locations: list[str] = []
                            
                            try:
                                user_id_obj = UserId.from_string(user_id)
                                people = await _neo4j_adapter.list_known_people(user_id_obj, limit=20)
                                existing_persons = [p.get("name", "") for p in people if p.get("name")]
                                
                                pets = await _neo4j_adapter.list_pets(user_id_obj)
                                existing_pets = [p.get("name", "") for p in pets if p.get("name")]
                                
                                locs = await _neo4j_adapter.list_locations(user_id_obj, limit=20)
                                existing_locations = [l.get("name", "") for l in locs if l.get("name")]
                            except Exception as fetch_err:
                                logger.debug(f"Could not fetch existing entities: {fetch_err}")
                            
                            # Extract entities from the message
                            entity_result = await extract_knowledge_from_text(
                                content,
                                api_key=api_key_for_entities,
                                context=recent_context if recent_context else None,
                                existing_persons=existing_persons,
                                existing_pets=existing_pets,
                                existing_locations=existing_locations,
                            )
                            
                            # Store extracted entities
                            user_id_obj = UserId.from_string(user_id)
                            
                            # Store persons
                            for person in entity_result.persons:
                                if person.confidence >= 0.7:
                                    await _neo4j_adapter.store_person(
                                        user_id=user_id_obj,
                                        name=person.name,
                                        aliases=person.aliases,
                                        relationship_type=person.relationship_type,
                                        context_notes=person.context_notes,
                                    )
                                    logger.debug(f"Stored person: {person.name}")
                            
                            # Store pets
                            for pet in entity_result.pets:
                                if pet.confidence >= 0.7:
                                    await _neo4j_adapter.store_pet(
                                        user_id=user_id_obj,
                                        name=pet.name,
                                        aliases=pet.aliases,
                                        species=pet.species,
                                        breed=pet.breed,
                                        personality=pet.traits,
                                        food_preferences=pet.food_preferences,
                                    )
                                    logger.debug(f"Stored pet: {pet.name}")
                            
                            # Store locations
                            for location in entity_result.locations:
                                if location.confidence >= 0.7:
                                    await _neo4j_adapter.store_location(
                                        user_id=user_id_obj,
                                        name=location.name,
                                        aliases=location.aliases,
                                        location_type=location.location_type,
                                        address=location.address,
                                        city=location.city,
                                        associated_activities=[location.associated_activity] if location.associated_activity else None,
                                    )
                                    logger.debug(f"Stored location: {location.name}")
                            
                            # Store preferences
                            for pref in entity_result.preferences:
                                if pref.confidence >= 0.7:
                                    sentiment = 0.8 if pref.sentiment == "likes" else (-0.8 if pref.sentiment == "dislikes" else 0.5)
                                    await _neo4j_adapter.store_preference(
                                        user_id=user_id_obj,
                                        category=pref.category,
                                        value=pref.value,
                                        sentiment=sentiment,
                                        subcategory=pref.subcategory,
                                        conversation_id=conversation_id,
                                    )
                                    logger.debug(f"Stored preference: {pref.category}/{pref.value}")
                            
                            # Create relationships between entities
                            for rel in entity_result.relationships:
                                if rel.confidence >= 0.7:
                                    await _neo4j_adapter.link_entities(
                                        user_id=user_id_obj,
                                        source_type=rel.source_type,
                                        source_name=rel.source_name,
                                        target_type=rel.target_type,
                                        target_name=rel.target_name,
                                        relationship=rel.relationship,
                                    )
                                    logger.debug(f"Linked: {rel.source_name} -{rel.relationship}-> {rel.target_name}")
                            
                            extracted_count = (
                                len([p for p in entity_result.persons if p.confidence >= 0.7]) +
                                len([p for p in entity_result.pets if p.confidence >= 0.7]) +
                                len([l for l in entity_result.locations if l.confidence >= 0.7]) +
                                len([p for p in entity_result.preferences if p.confidence >= 0.7])
                            )
                            if extracted_count > 0:
                                logger.info(f"Extracted {extracted_count} entities from message")
                        
                    except Exception as entity_err:
                        logger.debug(f"Entity extraction skipped: {entity_err}")
                
                elif msg_type == "typing":
                    await connection_manager.set_typing(
                        group_id, conversation_id, user_id, True
                    )
                
                elif msg_type == "stop_typing":
                    await connection_manager.set_typing(
                        group_id, conversation_id, user_id, False
                    )
                
                else:
                    # Unknown message type
                    await connection_manager.send_to_user(
                        group_id,
                        conversation_id,
                        user_id,
                        WebSocketMessage(
                            type=WebSocketMessageType.ERROR,
                            data={"message": f"Unknown message type: {msg_type}"},
                        ),
                    )
            
            except json.JSONDecodeError:
                await connection_manager.send_to_user(
                    group_id,
                    conversation_id,
                    user_id,
                    WebSocketMessage(
                        type=WebSocketMessageType.ERROR,
                        data={"message": "Invalid JSON"},
                    ),
                )
    
    except WebSocketDisconnect:
        await connection_manager.disconnect(group_id, conversation_id, user_id)
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {e}")
        await connection_manager.disconnect(group_id, conversation_id, user_id)
