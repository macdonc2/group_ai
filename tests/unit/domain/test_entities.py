"""Unit tests for domain entities."""

import pytest
from datetime import datetime

from agent_system.domain.entities import (
    User,
    UserPreferences,
    LearnedPattern,
    Conversation,
    Plan,
)
from agent_system.domain.value_objects import (
    UserId,
    ConversationId,
    Message,
    PlanGoal,
    PlanId,
    PlanStatus,
    PlanStep,
    StepStatus,
)


class TestUser:
    """Tests for User entity."""

    @pytest.mark.unit
    def test_user_creation(self):
        """Test creating a user."""
        user = User.create(
            email="test@example.com",
            hashed_password="hashed123",
        )
        assert user.email == "test@example.com"
        assert user.is_active is True
        assert user.is_verified is False
    
    @pytest.mark.unit
    def test_user_update_preferences(self):
        """Test updating user preferences."""
        user = User.create(email="test@example.com", hashed_password="hash")
        updated = user.update_preferences(temperature=0.5, auto_plan=False)
        
        assert updated.preferences.temperature == 0.5
        assert updated.preferences.auto_plan is False
        assert updated.updated_at > user.updated_at
    
    @pytest.mark.unit
    def test_user_add_learned_pattern(self):
        """Test adding a learned pattern."""
        user = User.create(email="test@example.com", hashed_password="hash")
        pattern = LearnedPattern(
            pattern_type="coding_style",
            description="Prefers functional programming",
            confidence=0.8,
        )
        updated = user.add_learned_pattern(pattern)
        
        assert len(updated.learned_patterns) == 1
        assert updated.learned_patterns[0].pattern_type == "coding_style"
    
    @pytest.mark.unit
    def test_user_get_pattern(self):
        """Test getting a learned pattern."""
        user = User.create(email="test@example.com", hashed_password="hash")
        pattern = LearnedPattern(
            pattern_type="coding_style",
            description="Prefers functional programming",
            confidence=0.8,
        )
        user = user.add_learned_pattern(pattern)
        
        found = user.get_pattern("coding_style")
        assert found is not None
        assert found.description == "Prefers functional programming"
        
        not_found = user.get_pattern("nonexistent")
        assert not_found is None
    
    @pytest.mark.unit
    def test_user_verify(self):
        """Test verifying a user."""
        user = User.create(email="test@example.com", hashed_password="hash")
        assert user.is_verified is False
        
        verified = user.verify()
        assert verified.is_verified is True


class TestConversation:
    """Tests for Conversation entity."""

    @pytest.mark.unit
    def test_conversation_creation(self):
        """Test creating a conversation."""
        user_id = UserId.generate()
        conv = Conversation.create(user_id=user_id, title="Test Chat")
        
        assert conv.user_id == user_id
        assert conv.metadata.title == "Test Chat"
        assert conv.message_count == 0
    
    @pytest.mark.unit
    def test_conversation_add_message(self):
        """Test adding messages to a conversation."""
        user_id = UserId.generate()
        conv = Conversation.create(user_id=user_id)
        
        msg = Message.user("Hello!")
        conv = conv.add_message(msg, token_count=5)
        
        assert conv.message_count == 1
        assert conv.metadata.total_tokens_used == 5
        assert conv.last_message is not None
        assert conv.last_message.message.content.text == "Hello!"
    
    @pytest.mark.unit
    def test_conversation_context_messages(self):
        """Test getting context window messages."""
        user_id = UserId.generate()
        conv = Conversation.create(user_id=user_id)
        conv = conv.model_copy(update={"context_window_size": 3})
        
        # Add more messages than context window
        for i in range(5):
            msg = Message.user(f"Message {i}")
            conv = conv.add_message(msg)
        
        context = conv.get_context_messages()
        assert len(context) == 3
        assert context[0].content.text == "Message 2"
        assert context[2].content.text == "Message 4"
    
    @pytest.mark.unit
    def test_conversation_set_active_plan(self):
        """Test setting active plan."""
        user_id = UserId.generate()
        conv = Conversation.create(user_id=user_id)
        plan_id = PlanId.generate()
        
        conv = conv.set_active_plan(plan_id)
        assert conv.active_plan_id == plan_id
        
        conv = conv.clear_active_plan()
        assert conv.active_plan_id is None
    
    @pytest.mark.unit
    def test_conversation_archive(self):
        """Test archiving a conversation."""
        user_id = UserId.generate()
        conv = Conversation.create(user_id=user_id)
        
        archived = conv.archive()
        assert archived.is_archived is True
        
        unarchived = archived.unarchive()
        assert unarchived.is_archived is False


class TestPlan:
    """Tests for Plan entity."""

    @pytest.fixture
    def sample_plan(self) -> Plan:
        """Create a sample plan for testing."""
        user_id = UserId.generate()
        conv_id = ConversationId.generate()
        goal = PlanGoal(
            description="Build a feature",
            success_criteria=["Feature works", "Tests pass"],
        )
        steps = [
            PlanStep(description="Design", order=0),
            PlanStep(description="Implement", order=1, dependencies=[0]),
            PlanStep(description="Test", order=2, dependencies=[1]),
        ]
        return Plan.create(
            user_id=user_id,
            conversation_id=conv_id,
            goal=goal,
            steps=steps,
        )

    @pytest.mark.unit
    def test_plan_creation(self, sample_plan: Plan):
        """Test creating a plan."""
        assert sample_plan.status == PlanStatus.DRAFT
        assert len(sample_plan.steps) == 3
        assert sample_plan.progress == 0.0
    
    @pytest.mark.unit
    def test_plan_activate(self, sample_plan: Plan):
        """Test activating a plan."""
        activated = sample_plan.activate()
        assert activated.status == PlanStatus.ACTIVE
        assert activated.is_active is True
    
    @pytest.mark.unit
    def test_plan_pause_resume(self, sample_plan: Plan):
        """Test pausing and resuming a plan."""
        plan = sample_plan.activate()
        paused = plan.pause()
        assert paused.status == PlanStatus.PAUSED
        
        resumed = paused.resume()
        assert resumed.status == PlanStatus.ACTIVE
    
    @pytest.mark.unit
    def test_plan_complete_steps(self, sample_plan: Plan):
        """Test completing plan steps."""
        plan = sample_plan.activate()
        
        # Start and complete first step
        plan = plan.start_current_step()
        assert plan.current_step.step.status == StepStatus.IN_PROGRESS
        
        plan = plan.complete_current_step("Design complete")
        assert plan.steps[0].step.status == StepStatus.COMPLETED
        assert plan.current_step_index == 1
        assert plan.progress == pytest.approx(33.33, rel=0.1)
    
    @pytest.mark.unit
    def test_plan_auto_complete(self, sample_plan: Plan):
        """Test that plan completes when all steps are done."""
        plan = sample_plan.activate()
        
        for i in range(3):
            plan = plan.start_current_step()
            plan = plan.complete_current_step(f"Step {i} done")
        
        assert plan.status == PlanStatus.COMPLETED
        assert plan.is_complete is True
        assert plan.progress == 100.0
    
    @pytest.mark.unit
    def test_plan_fail_step(self, sample_plan: Plan):
        """Test failing a plan step."""
        plan = sample_plan.activate().start_current_step()
        plan = plan.fail_current_step("Error occurred")
        
        assert plan.steps[0].step.status == StepStatus.FAILED
        assert plan.steps[0].step.error == "Error occurred"
    
    @pytest.mark.unit
    def test_plan_cancel(self, sample_plan: Plan):
        """Test canceling a plan."""
        plan = sample_plan.activate()
        canceled = plan.cancel()
        assert canceled.status == PlanStatus.CANCELLED
