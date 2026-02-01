"""SQLAlchemy repository implementations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agent_system.adapters.outbound.persistence.mappers import (
    ConversationMapper,
    MessageMapper,
    PlanMapper,
    PlanStepMapper,
    UserMapper,
)
from agent_system.adapters.outbound.persistence.models import (
    ConversationModel,
    MessageModel,
    PlanModel,
    PlanStepModel,
    UserModel,
)
from agent_system.domain.entities import Conversation, Plan, User
from agent_system.domain.ports import (
    ConversationRepository,
    PlanRepository,
    UserRepository,
)
from agent_system.domain.value_objects import ConversationId, PlanId, UserId


class SQLAlchemyUserRepository(UserRepository):
    """SQLAlchemy implementation of UserRepository."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with database session."""
        self._session = session

    async def get(self, id: UserId) -> User | None:
        """Get a user by ID."""
        result = await self._session.execute(
            select(UserModel).where(UserModel.id == str(id))
        )
        model = result.scalar_one_or_none()
        return UserMapper.to_entity(model) if model else None

    async def get_by_email(self, email: str) -> User | None:
        """Get a user by email address."""
        result = await self._session.execute(
            select(UserModel).where(UserModel.email == email)
        )
        model = result.scalar_one_or_none()
        return UserMapper.to_entity(model) if model else None

    async def save(self, user: User) -> User:
        """Save a new user."""
        model = UserMapper.to_model(user)
        self._session.add(model)
        await self._session.flush()
        return user

    async def update(self, user: User) -> User:
        """Update an existing user."""
        result = await self._session.execute(
            select(UserModel).where(UserModel.id == str(user.id))
        )
        model = result.scalar_one_or_none()
        if model:
            UserMapper.update_model(model, user)
            await self._session.flush()
        return user

    async def delete(self, id: UserId) -> bool:
        """Delete a user by ID."""
        result = await self._session.execute(
            select(UserModel).where(UserModel.id == str(id))
        )
        model = result.scalar_one_or_none()
        if model:
            await self._session.delete(model)
            await self._session.flush()
            return True
        return False

    async def exists(self, id: UserId) -> bool:
        """Check if a user exists."""
        result = await self._session.execute(
            select(UserModel.id).where(UserModel.id == str(id))
        )
        return result.scalar_one_or_none() is not None

    async def list_active(self, limit: int = 100, offset: int = 0) -> list[User]:
        """List active users with pagination."""
        result = await self._session.execute(
            select(UserModel)
            .where(UserModel.is_active == True)
            .order_by(UserModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return [UserMapper.to_entity(model) for model in result.scalars()]


class SQLAlchemyConversationRepository(ConversationRepository):
    """SQLAlchemy implementation of ConversationRepository."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with database session."""
        self._session = session

    async def get(self, id: ConversationId) -> Conversation | None:
        """Get a conversation by ID."""
        result = await self._session.execute(
            select(ConversationModel)
            .options(selectinload(ConversationModel.messages))
            .where(ConversationModel.id == str(id))
        )
        model = result.scalar_one_or_none()
        return ConversationMapper.to_entity(model) if model else None

    async def get_by_user(
        self,
        user_id: UserId,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Conversation]:
        """Get conversations for a user."""
        query = (
            select(ConversationModel)
            .options(selectinload(ConversationModel.messages))
            .where(ConversationModel.user_id == str(user_id))
        )
        if not include_archived:
            query = query.where(ConversationModel.is_archived == False)
        
        query = query.order_by(ConversationModel.updated_at.desc()).offset(offset).limit(limit)
        result = await self._session.execute(query)
        return [ConversationMapper.to_entity(model) for model in result.scalars()]

    async def get_active_for_user(self, user_id: UserId) -> Conversation | None:
        """Get the most recent active conversation for a user."""
        result = await self._session.execute(
            select(ConversationModel)
            .options(selectinload(ConversationModel.messages))
            .where(ConversationModel.user_id == str(user_id))
            .where(ConversationModel.is_archived == False)
            .order_by(ConversationModel.updated_at.desc())
            .limit(1)
        )
        model = result.scalar_one_or_none()
        return ConversationMapper.to_entity(model) if model else None

    async def save(self, conversation: Conversation) -> Conversation:
        """Save a new conversation."""
        model = ConversationMapper.to_model(conversation)
        self._session.add(model)
        
        # Save messages
        for stored_msg in conversation.messages:
            msg_model = MessageMapper.to_model(stored_msg, str(conversation.id))
            self._session.add(msg_model)
        
        await self._session.flush()
        return conversation

    async def update(self, conversation: Conversation) -> Conversation:
        """Update an existing conversation."""
        result = await self._session.execute(
            select(ConversationModel)
            .options(selectinload(ConversationModel.messages))
            .where(ConversationModel.id == str(conversation.id))
        )
        model = result.scalar_one_or_none()
        if model:
            ConversationMapper.update_model(model, conversation)
            
            # Get existing message IDs
            existing_msg_ids = {msg.id for msg in model.messages}
            
            # Add new messages
            for stored_msg in conversation.messages:
                if str(stored_msg.id) not in existing_msg_ids:
                    msg_model = MessageMapper.to_model(stored_msg, str(conversation.id))
                    self._session.add(msg_model)
            
            await self._session.flush()
        return conversation

    async def delete(self, id: ConversationId) -> bool:
        """Delete a conversation by ID."""
        result = await self._session.execute(
            select(ConversationModel).where(ConversationModel.id == str(id))
        )
        model = result.scalar_one_or_none()
        if model:
            await self._session.delete(model)
            await self._session.flush()
            return True
        return False

    async def exists(self, id: ConversationId) -> bool:
        """Check if a conversation exists."""
        result = await self._session.execute(
            select(ConversationModel.id).where(ConversationModel.id == str(id))
        )
        return result.scalar_one_or_none() is not None

    async def archive(self, conversation_id: ConversationId) -> bool:
        """Archive a conversation."""
        result = await self._session.execute(
            select(ConversationModel).where(ConversationModel.id == str(conversation_id))
        )
        model = result.scalar_one_or_none()
        if model:
            model.is_archived = True
            await self._session.flush()
            return True
        return False


class SQLAlchemyPlanRepository(PlanRepository):
    """SQLAlchemy implementation of PlanRepository."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with database session."""
        self._session = session

    async def get(self, id: PlanId) -> Plan | None:
        """Get a plan by ID."""
        result = await self._session.execute(
            select(PlanModel)
            .options(selectinload(PlanModel.steps))
            .where(PlanModel.id == str(id))
        )
        model = result.scalar_one_or_none()
        return PlanMapper.to_entity(model) if model else None

    async def get_by_user(
        self,
        user_id: UserId,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Plan]:
        """Get plans for a user."""
        result = await self._session.execute(
            select(PlanModel)
            .options(selectinload(PlanModel.steps))
            .where(PlanModel.user_id == str(user_id))
            .order_by(PlanModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return [PlanMapper.to_entity(model) for model in result.scalars()]

    async def get_by_conversation(
        self,
        conversation_id: ConversationId,
    ) -> list[Plan]:
        """Get plans for a conversation."""
        result = await self._session.execute(
            select(PlanModel)
            .options(selectinload(PlanModel.steps))
            .where(PlanModel.conversation_id == str(conversation_id))
            .order_by(PlanModel.created_at.desc())
        )
        return [PlanMapper.to_entity(model) for model in result.scalars()]

    async def get_active_for_conversation(
        self,
        conversation_id: ConversationId,
    ) -> Plan | None:
        """Get the active plan for a conversation."""
        result = await self._session.execute(
            select(PlanModel)
            .options(selectinload(PlanModel.steps))
            .where(PlanModel.conversation_id == str(conversation_id))
            .where(PlanModel.status == "active")
            .order_by(PlanModel.created_at.desc())
            .limit(1)
        )
        model = result.scalar_one_or_none()
        return PlanMapper.to_entity(model) if model else None

    async def save(self, plan: Plan) -> Plan:
        """Save a new plan."""
        model = PlanMapper.to_model(plan)
        self._session.add(model)
        
        # Save steps
        for stored_step in plan.steps:
            step_model = PlanStepMapper.to_model(stored_step, str(plan.id))
            self._session.add(step_model)
        
        await self._session.flush()
        return plan

    async def update(self, plan: Plan) -> Plan:
        """Update an existing plan."""
        result = await self._session.execute(
            select(PlanModel)
            .options(selectinload(PlanModel.steps))
            .where(PlanModel.id == str(plan.id))
        )
        model = result.scalar_one_or_none()
        if model:
            PlanMapper.update_model(model, plan)
            
            # Update existing steps and add new ones
            existing_step_ids = {step.id for step in model.steps}
            
            for stored_step in plan.steps:
                if str(stored_step.id) in existing_step_ids:
                    # Update existing step
                    for step_model in model.steps:
                        if step_model.id == str(stored_step.id):
                            step_model.description = stored_step.step.description
                            step_model.status = stored_step.step.status.value
                            step_model.result = stored_step.step.result
                            step_model.error = stored_step.step.error
                            step_model.started_at = stored_step.step.started_at
                            step_model.completed_at = stored_step.step.completed_at
                            step_model.step_metadata = stored_step.step.metadata
                            break
                else:
                    # Add new step
                    step_model = PlanStepMapper.to_model(stored_step, str(plan.id))
                    self._session.add(step_model)
            
            await self._session.flush()
        return plan

    async def delete(self, id: PlanId) -> bool:
        """Delete a plan by ID."""
        result = await self._session.execute(
            select(PlanModel).where(PlanModel.id == str(id))
        )
        model = result.scalar_one_or_none()
        if model:
            await self._session.delete(model)
            await self._session.flush()
            return True
        return False

    async def exists(self, id: PlanId) -> bool:
        """Check if a plan exists."""
        result = await self._session.execute(
            select(PlanModel.id).where(PlanModel.id == str(id))
        )
        return result.scalar_one_or_none() is not None
