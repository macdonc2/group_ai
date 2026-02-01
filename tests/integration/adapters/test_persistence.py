"""Integration tests for persistence adapters."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agent_system.adapters.outbound.persistence import (
    Base,
    SQLAlchemyUserRepository,
    SQLAlchemyConversationRepository,
    SQLAlchemyPlanRepository,
)
from agent_system.domain.entities import Conversation, Plan, User
from agent_system.domain.value_objects import (
    ConversationId,
    Message,
    PlanGoal,
    PlanId,
    PlanStep,
    UserId,
)


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Create an in-memory SQLite session for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    async with session_factory() as session:
        yield session
    
    await engine.dispose()


class TestUserRepository:
    """Integration tests for user repository."""

    @pytest.mark.integration
    async def test_save_and_get_user(self, db_session: AsyncSession):
        """Test saving and retrieving a user."""
        repo = SQLAlchemyUserRepository(db_session)
        
        user = User.create(
            email="test@example.com",
            hashed_password="hashed123",
        )
        
        await repo.save(user)
        await db_session.commit()
        
        retrieved = await repo.get(user.id)
        assert retrieved is not None
        assert retrieved.email == "test@example.com"
    
    @pytest.mark.integration
    async def test_get_user_by_email(self, db_session: AsyncSession):
        """Test getting user by email."""
        repo = SQLAlchemyUserRepository(db_session)
        
        user = User.create(
            email="unique@example.com",
            hashed_password="hashed123",
        )
        await repo.save(user)
        await db_session.commit()
        
        retrieved = await repo.get_by_email("unique@example.com")
        assert retrieved is not None
        assert retrieved.id == user.id
    
    @pytest.mark.integration
    async def test_update_user(self, db_session: AsyncSession):
        """Test updating a user."""
        repo = SQLAlchemyUserRepository(db_session)
        
        user = User.create(
            email="update@example.com",
            hashed_password="hashed123",
        )
        await repo.save(user)
        await db_session.commit()
        
        updated_user = user.update_preferences(temperature=0.5)
        await repo.update(updated_user)
        await db_session.commit()
        
        retrieved = await repo.get(user.id)
        assert retrieved is not None
        assert retrieved.preferences.temperature == 0.5
    
    @pytest.mark.integration
    async def test_delete_user(self, db_session: AsyncSession):
        """Test deleting a user."""
        repo = SQLAlchemyUserRepository(db_session)
        
        user = User.create(
            email="delete@example.com",
            hashed_password="hashed123",
        )
        await repo.save(user)
        await db_session.commit()
        
        success = await repo.delete(user.id)
        await db_session.commit()
        
        assert success is True
        assert await repo.get(user.id) is None
    
    @pytest.mark.integration
    async def test_list_active_users(self, db_session: AsyncSession):
        """Test listing active users."""
        repo = SQLAlchemyUserRepository(db_session)
        
        # Create active and inactive users
        active_user = User.create(
            email="active@example.com",
            hashed_password="hash",
        )
        inactive_user = User.create(
            email="inactive@example.com",
            hashed_password="hash",
        ).deactivate()
        
        await repo.save(active_user)
        await repo.save(inactive_user)
        await db_session.commit()
        
        active_users = await repo.list_active()
        assert len(active_users) == 1
        assert active_users[0].email == "active@example.com"


class TestConversationRepository:
    """Integration tests for conversation repository."""

    @pytest.mark.integration
    async def test_save_and_get_conversation(self, db_session: AsyncSession):
        """Test saving and retrieving a conversation."""
        # First create a user
        user_repo = SQLAlchemyUserRepository(db_session)
        user = User.create(email="conv@example.com", hashed_password="hash")
        await user_repo.save(user)
        await db_session.commit()
        
        # Now create conversation
        conv_repo = SQLAlchemyConversationRepository(db_session)
        conversation = Conversation.create(user_id=user.id, title="Test Chat")
        
        await conv_repo.save(conversation)
        await db_session.commit()
        
        retrieved = await conv_repo.get(conversation.id)
        assert retrieved is not None
        assert retrieved.metadata.title == "Test Chat"
    
    @pytest.mark.integration
    async def test_conversation_with_messages(self, db_session: AsyncSession):
        """Test conversation with messages."""
        # Create user
        user_repo = SQLAlchemyUserRepository(db_session)
        user = User.create(email="msg@example.com", hashed_password="hash")
        await user_repo.save(user)
        await db_session.commit()
        
        # Create conversation with messages
        conv_repo = SQLAlchemyConversationRepository(db_session)
        conversation = Conversation.create(user_id=user.id)
        conversation = conversation.add_message(Message.user("Hello!"))
        conversation = conversation.add_message(Message.assistant("Hi there!"))
        
        await conv_repo.save(conversation)
        await db_session.commit()
        
        retrieved = await conv_repo.get(conversation.id)
        assert retrieved is not None
        assert retrieved.message_count == 2
        assert retrieved.messages[0].message.content.text == "Hello!"
    
    @pytest.mark.integration
    async def test_get_conversations_by_user(self, db_session: AsyncSession):
        """Test getting conversations for a user."""
        # Create user
        user_repo = SQLAlchemyUserRepository(db_session)
        user = User.create(email="multi@example.com", hashed_password="hash")
        await user_repo.save(user)
        await db_session.commit()
        
        # Create multiple conversations
        conv_repo = SQLAlchemyConversationRepository(db_session)
        for i in range(3):
            conv = Conversation.create(user_id=user.id, title=f"Chat {i}")
            await conv_repo.save(conv)
        await db_session.commit()
        
        conversations = await conv_repo.get_by_user(user.id)
        assert len(conversations) == 3


class TestPlanRepository:
    """Integration tests for plan repository."""

    @pytest.mark.integration
    async def test_save_and_get_plan(self, db_session: AsyncSession):
        """Test saving and retrieving a plan."""
        # Create user
        user_repo = SQLAlchemyUserRepository(db_session)
        user = User.create(email="plan@example.com", hashed_password="hash")
        await user_repo.save(user)
        await db_session.commit()
        
        # Create plan
        plan_repo = SQLAlchemyPlanRepository(db_session)
        conv_id = ConversationId.generate()
        goal = PlanGoal(
            description="Build feature",
            success_criteria=["Works", "Tests pass"],
        )
        steps = [
            PlanStep(description="Step 1", order=0),
            PlanStep(description="Step 2", order=1),
        ]
        plan = Plan.create(
            user_id=user.id,
            conversation_id=conv_id,
            goal=goal,
            steps=steps,
        )
        
        await plan_repo.save(plan)
        await db_session.commit()
        
        retrieved = await plan_repo.get(plan.id)
        assert retrieved is not None
        assert retrieved.goal.description == "Build feature"
        assert len(retrieved.steps) == 2
    
    @pytest.mark.integration
    async def test_update_plan_status(self, db_session: AsyncSession):
        """Test updating plan status."""
        # Create user
        user_repo = SQLAlchemyUserRepository(db_session)
        user = User.create(email="status@example.com", hashed_password="hash")
        await user_repo.save(user)
        await db_session.commit()
        
        # Create plan
        plan_repo = SQLAlchemyPlanRepository(db_session)
        plan = Plan.create(
            user_id=user.id,
            conversation_id=ConversationId.generate(),
            goal=PlanGoal(description="Test", success_criteria=[]),
        )
        await plan_repo.save(plan)
        await db_session.commit()
        
        # Activate and update
        plan = plan.activate()
        await plan_repo.update(plan)
        await db_session.commit()
        
        retrieved = await plan_repo.get(plan.id)
        assert retrieved is not None
        assert retrieved.is_active is True
