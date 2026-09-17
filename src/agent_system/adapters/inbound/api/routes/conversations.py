"""Conversation API routes."""

from fastapi import APIRouter, HTTPException, status

from agent_system.adapters.inbound.api.dependencies import (
    CurrentUserId,
    SessionDep,
    require_conversation_access,
)
from agent_system.adapters.inbound.api.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationRead,
    ConversationUpdate,
    MessageRead,
)
from agent_system.adapters.outbound.persistence import SQLAlchemyConversationRepository
from agent_system.domain.entities import Conversation
from agent_system.domain.value_objects import ConversationId, UserId

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationRead])
async def list_conversations(
    current_user_id: CurrentUserId,
    session: SessionDep,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[ConversationRead]:
    """List conversations for the current user."""
    repo = SQLAlchemyConversationRepository(session)
    conversations = await repo.get_by_user(
        UserId.from_string(current_user_id),
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )
    
    return [
        ConversationRead(
            id=str(conv.id),
            user_id=str(conv.user_id),
            title=conv.metadata.title,
            summary=conv.metadata.summary,
            message_count=conv.message_count,
            is_archived=conv.is_archived,
            active_plan_id=str(conv.active_plan_id) if conv.active_plan_id else None,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            persona=conv.persona,
        )
        for conv in conversations
    ]


@router.post("", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    data: ConversationCreate,
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> ConversationRead:
    """Create a new conversation."""
    repo = SQLAlchemyConversationRepository(session)
    
    conversation = Conversation.create(
        user_id=UserId.from_string(current_user_id),
        title=data.title,
    )
    
    await repo.save(conversation)
    
    return ConversationRead(
        id=str(conversation.id),
        user_id=str(conversation.user_id),
        title=conversation.metadata.title,
        summary=conversation.metadata.summary,
        message_count=conversation.message_count,
        is_archived=conversation.is_archived,
        active_plan_id=str(conversation.active_plan_id) if conversation.active_plan_id else None,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        persona=conversation.persona,
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> ConversationDetail:
    """Get a conversation with its messages."""
    await require_conversation_access(conversation_id, current_user_id, session)
    
    repo = SQLAlchemyConversationRepository(session)
    conversation = await repo.get(ConversationId.from_string(conversation_id))
    
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    
    messages = [
        MessageRead(
            id=str(stored.id),
            role=stored.message.role.value,
            content=stored.message.content.text,
            timestamp=stored.message.timestamp,
            tool_calls=[tc.model_dump() for tc in stored.message.tool_calls],
        )
        for stored in conversation.messages
    ]
    
    return ConversationDetail(
        id=str(conversation.id),
        user_id=str(conversation.user_id),
        title=conversation.metadata.title,
        summary=conversation.metadata.summary,
        message_count=conversation.message_count,
        is_archived=conversation.is_archived,
        active_plan_id=str(conversation.active_plan_id) if conversation.active_plan_id else None,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        persona=conversation.persona,
        messages=messages,
    )


@router.patch("/{conversation_id}", response_model=ConversationRead)
async def update_conversation(
    conversation_id: str,
    data: ConversationUpdate,
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> ConversationRead:
    """Update a conversation."""
    await require_conversation_access(conversation_id, current_user_id, session)
    
    repo = SQLAlchemyConversationRepository(session)
    conversation = await repo.get(ConversationId.from_string(conversation_id))
    
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    
    # Update fields
    updates = {}
    if data.title is not None:
        updates["title"] = data.title
    if data.summary is not None:
        updates["summary"] = data.summary
    if data.tags is not None:
        updates["tags"] = data.tags
    
    if updates:
        conversation = conversation.update_metadata(**updates)
    if data.persona is not None:
        from agent_system.adapters.outbound.llm.personas import is_valid_persona
        wanted = data.persona.strip().lower()
        if wanted and wanted != "none" and not is_valid_persona(wanted):
            raise HTTPException(status_code=422, detail=f"Unknown persona '{data.persona}'")
        conversation = conversation.with_persona(wanted if wanted and wanted != "none" else None)
        updates["persona"] = wanted
    if updates:
        await repo.update(conversation)
    
    return ConversationRead(
        id=str(conversation.id),
        user_id=str(conversation.user_id),
        title=conversation.metadata.title,
        summary=conversation.metadata.summary,
        message_count=conversation.message_count,
        is_archived=conversation.is_archived,
        active_plan_id=str(conversation.active_plan_id) if conversation.active_plan_id else None,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        persona=conversation.persona,
    )


@router.post("/{conversation_id}/archive", response_model=ConversationRead)
async def archive_conversation(
    conversation_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> ConversationRead:
    """Archive a conversation."""
    await require_conversation_access(conversation_id, current_user_id, session)
    
    repo = SQLAlchemyConversationRepository(session)
    success = await repo.archive(ConversationId.from_string(conversation_id))
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    
    conversation = await repo.get(ConversationId.from_string(conversation_id))
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    
    return ConversationRead(
        id=str(conversation.id),
        user_id=str(conversation.user_id),
        title=conversation.metadata.title,
        summary=conversation.metadata.summary,
        message_count=conversation.message_count,
        is_archived=conversation.is_archived,
        active_plan_id=str(conversation.active_plan_id) if conversation.active_plan_id else None,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        persona=conversation.persona,
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> None:
    """Delete a conversation."""
    await require_conversation_access(conversation_id, current_user_id, session)
    
    repo = SQLAlchemyConversationRepository(session)
    success = await repo.delete(ConversationId.from_string(conversation_id))
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
