"""Mappers between domain entities and SQLAlchemy models."""

from agent_system.adapters.outbound.persistence.models import (
    ConversationModel,
    ExtractedEventModel,
    GroupConversationModel,
    GroupMembershipModel,
    GroupMessageModel,
    GroupModel,
    MessageModel,
    PlanModel,
    PlanStepModel,
    UserModel,
)
from agent_system.domain.entities import (
    Conversation,
    ConversationMetadata,
    EventType,
    ExtractedEvent,
    Group,
    GroupConversation,
    GroupConversationMetadata,
    GroupMembership,
    MemberRole,
    Plan,
    StoredGroupMessage,
    StoredMessage,
    StoredPlanStep,
    User,
    UserPreferences,
    LearnedPattern,
)
from agent_system.domain.value_objects import (
    ConversationId,
    EventId,
    GroupConversationId,
    GroupId,
    GroupMembershipId,
    Message,
    MessageContent,
    MessageId,
    MessageRole,
    PlanGoal,
    PlanId,
    PlanStatus,
    PlanStep,
    PlanStepId,
    StepStatus,
    ToolCall,
    UserId,
)


class UserMapper:
    """Maps between User domain entity and UserModel."""

    @staticmethod
    def to_model(user: User) -> UserModel:
        """Convert domain entity to ORM model."""
        return UserModel(
            id=str(user.id),
            email=user.email,
            hashed_password=user.hashed_password,
            is_active=user.is_active,
            is_superuser=user.is_superuser,
            is_verified=user.is_verified,
            encrypted_openai_api_key=user.encrypted_openai_api_key,
            encrypted_google_refresh_token=user.encrypted_google_refresh_token,
            google_calendar_email=user.google_calendar_email,
            timezone=user.timezone,
            preferences=user.preferences.model_dump(),
            learned_patterns=[p.model_dump(mode="json") for p in user.learned_patterns],
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

    @staticmethod
    def to_entity(model: UserModel) -> User:
        """Convert ORM model to domain entity."""
        return User(
            id=UserId.from_string(model.id),
            email=model.email,
            hashed_password=model.hashed_password,
            is_active=model.is_active,
            is_superuser=model.is_superuser,
            is_verified=model.is_verified,
            encrypted_openai_api_key=model.encrypted_openai_api_key,
            encrypted_google_refresh_token=getattr(model, 'encrypted_google_refresh_token', None),
            google_calendar_email=getattr(model, 'google_calendar_email', None),
            timezone=getattr(model, 'timezone', 'UTC'),  # Fallback for existing users
            preferences=UserPreferences(**model.preferences),
            learned_patterns=[LearnedPattern(**p) for p in model.learned_patterns],
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    @staticmethod
    def update_model(model: UserModel, user: User) -> UserModel:
        """Update ORM model from domain entity."""
        model.email = user.email
        model.hashed_password = user.hashed_password
        model.is_active = user.is_active
        model.is_superuser = user.is_superuser
        model.is_verified = user.is_verified
        model.encrypted_openai_api_key = user.encrypted_openai_api_key
        model.encrypted_google_refresh_token = user.encrypted_google_refresh_token
        model.google_calendar_email = user.google_calendar_email
        model.timezone = user.timezone
        model.preferences = user.preferences.model_dump()
        model.learned_patterns = [p.model_dump(mode="json") for p in user.learned_patterns]
        model.updated_at = user.updated_at
        return model


class MessageMapper:
    """Maps between Message value objects and MessageModel."""

    @staticmethod
    def to_model(stored: StoredMessage, conversation_id: str) -> MessageModel:
        """Convert stored message to ORM model."""
        return MessageModel(
            id=str(stored.id),
            conversation_id=conversation_id,
            role=stored.message.role.value,
            content=stored.message.content.text,
            content_metadata=stored.message.content.metadata,
            tool_calls=[tc.model_dump() for tc in stored.message.tool_calls],
            token_count=stored.token_count,
            created_at=stored.message.timestamp,
        )

    @staticmethod
    def to_stored_message(model: MessageModel) -> StoredMessage:
        """Convert ORM model to stored message."""
        message = Message(
            role=MessageRole(model.role),
            content=MessageContent(
                text=model.content,
                metadata=model.content_metadata,
            ),
            tool_calls=[ToolCall(**tc) for tc in model.tool_calls],
            timestamp=model.created_at,
        )
        return StoredMessage(
            id=MessageId.from_string(model.id),
            message=message,
            token_count=model.token_count,
        )


class ConversationMapper:
    """Maps between Conversation domain entity and ConversationModel."""

    @staticmethod
    def to_model(conversation: Conversation) -> ConversationModel:
        """Convert domain entity to ORM model."""
        return ConversationModel(
            id=str(conversation.id),
            user_id=str(conversation.user_id),
            active_plan_id=str(conversation.active_plan_id) if conversation.active_plan_id else None,
            title=conversation.metadata.title,
            summary=conversation.metadata.summary,
            tags=conversation.metadata.tags,
            topic_keywords=conversation.metadata.topic_keywords,
            total_tokens_used=conversation.metadata.total_tokens_used,
            context_window_size=conversation.context_window_size,
            custom_data=conversation.metadata.custom_data,
            is_archived=conversation.is_archived,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )

    @staticmethod
    def to_entity(model: ConversationModel) -> Conversation:
        """Convert ORM model to domain entity."""
        messages = [
            MessageMapper.to_stored_message(msg)
            for msg in model.messages
        ]
        return Conversation(
            id=ConversationId.from_string(model.id),
            user_id=UserId.from_string(model.user_id),
            messages=messages,
            active_plan_id=PlanId.from_string(model.active_plan_id) if model.active_plan_id else None,
            metadata=ConversationMetadata(
                title=model.title,
                summary=model.summary,
                tags=model.tags,
                topic_keywords=model.topic_keywords,
                total_tokens_used=model.total_tokens_used,
                custom_data=model.custom_data,
            ),
            context_window_size=model.context_window_size,
            created_at=model.created_at,
            updated_at=model.updated_at,
            is_archived=model.is_archived,
        )

    @staticmethod
    def update_model(model: ConversationModel, conversation: Conversation) -> ConversationModel:
        """Update ORM model from domain entity."""
        model.active_plan_id = str(conversation.active_plan_id) if conversation.active_plan_id else None
        model.title = conversation.metadata.title
        model.summary = conversation.metadata.summary
        model.tags = conversation.metadata.tags
        model.topic_keywords = conversation.metadata.topic_keywords
        model.total_tokens_used = conversation.metadata.total_tokens_used
        model.context_window_size = conversation.context_window_size
        model.custom_data = conversation.metadata.custom_data
        model.is_archived = conversation.is_archived
        model.updated_at = conversation.updated_at
        return model


class PlanStepMapper:
    """Maps between PlanStep value objects and PlanStepModel."""

    @staticmethod
    def to_model(stored: StoredPlanStep, plan_id: str) -> PlanStepModel:
        """Convert stored plan step to ORM model."""
        return PlanStepModel(
            id=str(stored.id),
            plan_id=plan_id,
            description=stored.step.description,
            status=stored.step.status.value,
            order=stored.step.order,
            dependencies=stored.step.dependencies,
            tool_required=stored.step.tool_required,
            result=stored.step.result,
            error=stored.step.error,
            step_metadata=stored.step.metadata,
            started_at=stored.step.started_at,
            completed_at=stored.step.completed_at,
        )

    @staticmethod
    def to_stored_step(model: PlanStepModel) -> StoredPlanStep:
        """Convert ORM model to stored plan step."""
        step = PlanStep(
            description=model.description,
            status=StepStatus(model.status),
            order=model.order,
            dependencies=model.dependencies,
            tool_required=model.tool_required,
            result=model.result,
            error=model.error,
            metadata=model.step_metadata,
            started_at=model.started_at,
            completed_at=model.completed_at,
        )
        return StoredPlanStep(
            id=PlanStepId.from_string(model.id),
            step=step,
        )


class PlanMapper:
    """Maps between Plan domain entity and PlanModel."""

    @staticmethod
    def to_model(plan: Plan) -> PlanModel:
        """Convert domain entity to ORM model."""
        return PlanModel(
            id=str(plan.id),
            user_id=str(plan.user_id),
            conversation_id=str(plan.conversation_id),
            goal_description=plan.goal.description,
            goal_success_criteria=plan.goal.success_criteria,
            goal_context=plan.goal.context,
            status=plan.status.value,
            current_step_index=plan.current_step_index,
            plan_metadata=plan.metadata,
            created_at=plan.created_at,
            updated_at=plan.updated_at,
            completed_at=plan.completed_at,
        )

    @staticmethod
    def to_entity(model: PlanModel) -> Plan:
        """Convert ORM model to domain entity."""
        steps = [
            PlanStepMapper.to_stored_step(step)
            for step in model.steps
        ]
        return Plan(
            id=PlanId.from_string(model.id),
            user_id=UserId.from_string(model.user_id),
            conversation_id=ConversationId.from_string(model.conversation_id),
            goal=PlanGoal(
                description=model.goal_description,
                success_criteria=model.goal_success_criteria,
                context=model.goal_context,
            ),
            steps=steps,
            status=PlanStatus(model.status),
            current_step_index=model.current_step_index,
            metadata=model.plan_metadata,
            created_at=model.created_at,
            updated_at=model.updated_at,
            completed_at=model.completed_at,
        )

    @staticmethod
    def update_model(model: PlanModel, plan: Plan) -> PlanModel:
        """Update ORM model from domain entity."""
        model.goal_description = plan.goal.description
        model.goal_success_criteria = plan.goal.success_criteria
        model.goal_context = plan.goal.context
        model.status = plan.status.value
        model.current_step_index = plan.current_step_index
        model.plan_metadata = plan.metadata
        model.updated_at = plan.updated_at
        model.completed_at = plan.completed_at
        return model


# ==================== Group Mappers ====================


class GroupMembershipMapper:
    """Maps between GroupMembership domain entity and GroupMembershipModel."""

    @staticmethod
    def to_model(membership: GroupMembership) -> GroupMembershipModel:
        """Convert domain entity to ORM model."""
        return GroupMembershipModel(
            id=str(membership.id),
            user_id=str(membership.user_id),
            group_id=str(membership.group_id),
            role=membership.role.value,
            sharing_enabled=membership.sharing_enabled,
            joined_at=membership.joined_at,
            last_seen_at=membership.last_seen_at,
        )

    @staticmethod
    def to_entity(model: GroupMembershipModel) -> GroupMembership:
        """Convert ORM model to domain entity."""
        return GroupMembership(
            id=GroupMembershipId.from_string(model.id),
            user_id=UserId.from_string(model.user_id),
            group_id=GroupId.from_string(model.group_id),
            role=MemberRole(model.role),
            sharing_enabled=model.sharing_enabled,
            joined_at=model.joined_at,
            last_seen_at=model.last_seen_at,
        )

    @staticmethod
    def update_model(model: GroupMembershipModel, membership: GroupMembership) -> GroupMembershipModel:
        """Update ORM model from domain entity."""
        model.sharing_enabled = membership.sharing_enabled
        model.last_seen_at = membership.last_seen_at
        return model


class GroupMapper:
    """Maps between Group domain entity and GroupModel."""

    @staticmethod
    def to_model(group: Group) -> GroupModel:
        """Convert domain entity to ORM model."""
        return GroupModel(
            id=str(group.id),
            name=group.name,
            description=group.description,
            created_by=str(group.created_by),
            created_at=group.created_at,
            updated_at=group.updated_at,
        )

    @staticmethod
    def to_entity(model: GroupModel) -> Group:
        """Convert ORM model to domain entity."""
        memberships = [
            GroupMembershipMapper.to_entity(m)
            for m in model.memberships
        ]
        return Group(
            id=GroupId.from_string(model.id),
            name=model.name,
            description=model.description,
            created_by=UserId.from_string(model.created_by),
            members=memberships,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    @staticmethod
    def update_model(model: GroupModel, group: Group) -> GroupModel:
        """Update ORM model from domain entity."""
        model.name = group.name
        model.description = group.description
        model.updated_at = group.updated_at
        return model


class GroupMessageMapper:
    """Maps between StoredGroupMessage and GroupMessageModel."""

    @staticmethod
    def to_model(stored: StoredGroupMessage, group_conversation_id: str) -> GroupMessageModel:
        """Convert stored group message to ORM model."""
        return GroupMessageModel(
            id=str(stored.id),
            group_conversation_id=group_conversation_id,
            sender_id=str(stored.sender_id),
            role=stored.message.role.value,
            content=stored.message.content.text,
            content_metadata=stored.message.content.metadata,
            tool_calls=[tc.model_dump() for tc in stored.message.tool_calls],
            token_count=stored.token_count,
            created_at=stored.message.timestamp,
        )

    @staticmethod
    def to_stored_message(model: GroupMessageModel) -> StoredGroupMessage:
        """Convert ORM model to stored group message."""
        message = Message(
            role=MessageRole(model.role),
            content=MessageContent(
                text=model.content,
                metadata=model.content_metadata,
            ),
            tool_calls=[ToolCall(**tc) for tc in model.tool_calls],
            timestamp=model.created_at,
        )
        return StoredGroupMessage(
            id=MessageId.from_string(model.id),
            message=message,
            sender_id=UserId.from_string(model.sender_id),
            token_count=model.token_count,
        )


class GroupConversationMapper:
    """Maps between GroupConversation domain entity and GroupConversationModel."""

    @staticmethod
    def to_model(conversation: GroupConversation) -> GroupConversationModel:
        """Convert domain entity to ORM model."""
        return GroupConversationModel(
            id=str(conversation.id),
            group_id=str(conversation.group_id),
            title=conversation.metadata.title,
            summary=conversation.metadata.summary,
            tags=conversation.metadata.tags,
            topic_keywords=conversation.metadata.topic_keywords,
            total_tokens_used=conversation.metadata.total_tokens_used,
            context_window_size=conversation.context_window_size,
            participant_ids=[str(p) for p in conversation.participant_ids],
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )

    @staticmethod
    def to_entity(model: GroupConversationModel) -> GroupConversation:
        """Convert ORM model to domain entity."""
        messages = [
            GroupMessageMapper.to_stored_message(msg)
            for msg in model.messages
        ]
        return GroupConversation(
            id=GroupConversationId.from_string(model.id),
            group_id=GroupId.from_string(model.group_id),
            messages=messages,
            participant_ids=[UserId.from_string(p) for p in model.participant_ids],
            metadata=GroupConversationMetadata(
                title=model.title,
                summary=model.summary,
                tags=model.tags,
                topic_keywords=model.topic_keywords,
                total_tokens_used=model.total_tokens_used,
            ),
            context_window_size=model.context_window_size,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    @staticmethod
    def update_model(model: GroupConversationModel, conversation: GroupConversation) -> GroupConversationModel:
        """Update ORM model from domain entity."""
        model.title = conversation.metadata.title
        model.summary = conversation.metadata.summary
        model.tags = conversation.metadata.tags
        model.topic_keywords = conversation.metadata.topic_keywords
        model.total_tokens_used = conversation.metadata.total_tokens_used
        model.context_window_size = conversation.context_window_size
        model.participant_ids = [str(p) for p in conversation.participant_ids]
        model.updated_at = conversation.updated_at
        return model


class ExtractedEventMapper:
    """Maps between ExtractedEvent domain entity and ExtractedEventModel."""

    @staticmethod
    def to_model(event: ExtractedEvent) -> ExtractedEventModel:
        """Convert domain entity to ORM model."""
        return ExtractedEventModel(
            id=str(event.id),
            group_id=str(event.group_id),
            title=event.title,
            description=event.description,
            event_type=event.event_type.value,
            event_datetime=event.event_datetime,
            location=event.location,
            source_message_id=str(event.source_message_id) if event.source_message_id else None,
            confidence=event.confidence,
            is_confirmed=event.is_confirmed,
            participant_ids=[str(p) for p in event.participant_ids],
            created_at=event.created_at,
            google_event_id=event.google_event_id,
            google_calendar_id=event.google_calendar_id,
            google_sync_status=event.google_sync_status.value,
            google_synced_at=event.google_synced_at,
        )

    @staticmethod
    def to_entity(model: ExtractedEventModel) -> ExtractedEvent:
        """Convert ORM model to domain entity."""
        from agent_system.domain.entities.extracted_event import GoogleCalendarSyncStatus
        
        return ExtractedEvent(
            id=EventId.from_string(model.id),
            group_id=GroupId.from_string(model.group_id),
            title=model.title,
            description=model.description,
            event_type=EventType(model.event_type),
            event_datetime=model.event_datetime,
            location=model.location,
            source_message_id=MessageId.from_string(model.source_message_id) if model.source_message_id else None,
            confidence=model.confidence,
            is_confirmed=model.is_confirmed,
            participant_ids=[UserId.from_string(p) for p in model.participant_ids],
            created_at=model.created_at,
            google_event_id=model.google_event_id,
            google_calendar_id=model.google_calendar_id,
            google_sync_status=GoogleCalendarSyncStatus(model.google_sync_status) if model.google_sync_status else GoogleCalendarSyncStatus.PENDING,
            google_synced_at=model.google_synced_at,
        )

    @staticmethod
    def update_model(model: ExtractedEventModel, event: ExtractedEvent) -> ExtractedEventModel:
        """Update ORM model from domain entity."""
        model.title = event.title
        model.description = event.description
        model.event_datetime = event.event_datetime
        model.location = event.location
        model.is_confirmed = event.is_confirmed
        model.participant_ids = [str(p) for p in event.participant_ids]
        model.google_event_id = event.google_event_id
        model.google_calendar_id = event.google_calendar_id
        model.google_sync_status = event.google_sync_status.value
        model.google_synced_at = event.google_synced_at
        return model
