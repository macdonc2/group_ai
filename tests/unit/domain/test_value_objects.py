"""Unit tests for domain value objects."""

import pytest
from uuid import UUID

from agent_system.domain.value_objects import (
    UserId,
    ConversationId,
    MessageId,
    PlanId,
    PlanStepId,
    Message,
    MessageContent,
    MessageRole,
    PlanStep,
    StepStatus,
    PlanGoal,
    Intent,
    IntentType,
    Entity,
    EntityType,
)


class TestIdentifiers:
    """Tests for identifier value objects."""

    @pytest.mark.unit
    def test_user_id_generation(self):
        """Test that user IDs are generated correctly."""
        user_id = UserId.generate()
        assert isinstance(user_id.value, UUID)
    
    @pytest.mark.unit
    def test_user_id_from_string(self):
        """Test creating user ID from string."""
        uuid_str = "12345678-1234-5678-1234-567812345678"
        user_id = UserId.from_string(uuid_str)
        assert str(user_id) == uuid_str
    
    @pytest.mark.unit
    def test_user_id_equality(self):
        """Test user ID equality."""
        uuid_str = "12345678-1234-5678-1234-567812345678"
        id1 = UserId.from_string(uuid_str)
        id2 = UserId.from_string(uuid_str)
        assert id1 == id2
    
    @pytest.mark.unit
    def test_user_id_hash(self):
        """Test user ID hashing for use in sets/dicts."""
        user_id = UserId.generate()
        id_set = {user_id}
        assert user_id in id_set
    
    @pytest.mark.unit
    def test_conversation_id_generation(self):
        """Test conversation ID generation."""
        conv_id = ConversationId.generate()
        assert isinstance(conv_id.value, UUID)
    
    @pytest.mark.unit
    def test_message_id_generation(self):
        """Test message ID generation."""
        msg_id = MessageId.generate()
        assert isinstance(msg_id.value, UUID)
    
    @pytest.mark.unit
    def test_plan_id_generation(self):
        """Test plan ID generation."""
        plan_id = PlanId.generate()
        assert isinstance(plan_id.value, UUID)


class TestMessage:
    """Tests for Message value object."""

    @pytest.mark.unit
    def test_user_message_creation(self):
        """Test creating a user message."""
        msg = Message.user("Hello, world!")
        assert msg.role == MessageRole.USER
        assert msg.content.text == "Hello, world!"
    
    @pytest.mark.unit
    def test_assistant_message_creation(self):
        """Test creating an assistant message."""
        msg = Message.assistant("I can help with that.")
        assert msg.role == MessageRole.ASSISTANT
        assert msg.content.text == "I can help with that."
    
    @pytest.mark.unit
    def test_system_message_creation(self):
        """Test creating a system message."""
        msg = Message.system("You are a helpful assistant.")
        assert msg.role == MessageRole.SYSTEM
        assert msg.content.text == "You are a helpful assistant."
    
    @pytest.mark.unit
    def test_message_content_truncation(self):
        """Test message content truncation."""
        content = MessageContent(text="A" * 100)
        truncated = content.truncate(50)
        assert len(truncated.text) == 53  # 50 + "..."
        assert truncated.metadata["truncated"] is True
        assert truncated.metadata["original_length"] == 100
    
    @pytest.mark.unit
    def test_message_content_no_truncation_needed(self):
        """Test that short content is not truncated."""
        content = MessageContent(text="Short text")
        truncated = content.truncate(100)
        assert truncated.text == "Short text"
        assert "truncated" not in truncated.metadata


class TestPlanStep:
    """Tests for PlanStep value object."""

    @pytest.mark.unit
    def test_plan_step_creation(self):
        """Test creating a plan step."""
        step = PlanStep(
            description="Complete the task",
            order=0,
        )
        assert step.description == "Complete the task"
        assert step.status == StepStatus.PENDING
        assert step.order == 0
    
    @pytest.mark.unit
    def test_plan_step_start(self):
        """Test starting a plan step."""
        step = PlanStep(description="Task", order=0)
        started = step.start()
        assert started.status == StepStatus.IN_PROGRESS
        assert started.started_at is not None
    
    @pytest.mark.unit
    def test_plan_step_complete(self):
        """Test completing a plan step."""
        step = PlanStep(description="Task", order=0).start()
        completed = step.complete("Done!")
        assert completed.status == StepStatus.COMPLETED
        assert completed.result == "Done!"
        assert completed.completed_at is not None
    
    @pytest.mark.unit
    def test_plan_step_fail(self):
        """Test failing a plan step."""
        step = PlanStep(description="Task", order=0).start()
        failed = step.fail("Error occurred")
        assert failed.status == StepStatus.FAILED
        assert failed.error == "Error occurred"
    
    @pytest.mark.unit
    def test_plan_step_can_start_no_dependencies(self):
        """Test that step with no dependencies can start."""
        step = PlanStep(description="Task", order=0)
        assert step.can_start(set()) is True
    
    @pytest.mark.unit
    def test_plan_step_can_start_with_dependencies(self):
        """Test step dependency checking."""
        step = PlanStep(description="Task", order=2, dependencies=[0, 1])
        assert step.can_start({0}) is False
        assert step.can_start({0, 1}) is True
        assert step.can_start({0, 1, 2}) is True


class TestPlanGoal:
    """Tests for PlanGoal value object."""

    @pytest.mark.unit
    def test_plan_goal_creation(self):
        """Test creating a plan goal."""
        goal = PlanGoal(
            description="Build a website",
            success_criteria=["Homepage loads", "All links work"],
        )
        assert goal.description == "Build a website"
        assert len(goal.success_criteria) == 2


class TestIntent:
    """Tests for Intent value object."""

    @pytest.mark.unit
    def test_intent_creation(self):
        """Test creating an intent."""
        intent = Intent(
            intent_type=IntentType.QUESTION,
            description="User wants to know about Python",
            confidence=0.9,
        )
        assert intent.intent_type == IntentType.QUESTION
        assert intent.confidence == 0.9
    
    @pytest.mark.unit
    def test_intent_high_confidence(self):
        """Test high confidence detection."""
        high = Intent(intent_type=IntentType.TASK, description="Test", confidence=0.85)
        low = Intent(intent_type=IntentType.TASK, description="Test", confidence=0.5)
        assert high.is_high_confidence() is True
        assert low.is_high_confidence() is False


class TestEntity:
    """Tests for Entity value object."""

    @pytest.mark.unit
    def test_entity_creation(self):
        """Test creating an entity."""
        entity = Entity(
            entity_type=EntityType.TOPIC,
            value="Python",
            context="Programming language",
        )
        assert entity.entity_type == EntityType.TOPIC
        assert entity.value == "Python"
        assert entity.confidence == 1.0  # Default
