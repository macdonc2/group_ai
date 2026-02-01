"""Application service layer - orchestrates use cases."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from agent_system.adapters.outbound.fsm import (
    WorkflowResult,
    WorkflowState,
    run_agent_workflow,
)
from agent_system.composition_root.container import Container
from agent_system.domain.entities import Conversation, Plan, User
from agent_system.domain.value_objects import (
    ConversationId,
    Message,
    PlanGoal,
    PlanId,
    PlanStep,
    UserId,
)


@dataclass
class AgentService:
    """Service for agent interactions.
    
    Orchestrates the agent workflow and manages conversations.
    """

    container: Container
    session: AsyncSession

    async def chat(
        self,
        user_id: UserId,
        message: str,
        conversation_id: ConversationId | None = None,
    ) -> tuple[str, Conversation, list[dict]]:
        """Process a chat message through the agent workflow.
        
        Args:
            user_id: The user's ID
            message: The user's message
            conversation_id: Optional existing conversation ID
            
        Returns:
            Tuple of (response, conversation, suggestions)
        """
        user_repo = self.container.get_user_repository(self.session)
        conv_repo = self.container.get_conversation_repository(self.session)
        
        # Get user
        user = await user_repo.get(user_id)
        if not user:
            raise ValueError(f"User not found: {user_id}")
        
        # Get or create conversation
        if conversation_id:
            conversation = await conv_repo.get(conversation_id)
            if not conversation:
                raise ValueError(f"Conversation not found: {conversation_id}")
        else:
            conversation = Conversation.create(user_id=user_id)
            await conv_repo.save(conversation)
        
        # Add user message
        user_message = Message.user(message)
        conversation = conversation.add_message(user_message)
        
        # Get active plan if any
        current_plan = None
        if conversation.active_plan_id:
            plan_repo = self.container.get_plan_repository(self.session)
            current_plan = await plan_repo.get(conversation.active_plan_id)
        
        # Create workflow state
        state = WorkflowState(
            user=user,
            conversation=conversation,
            current_plan=current_plan,
        )
        
        # Get dependencies
        deps = self.container.get_agent_dependencies(self.session)
        
        # Run workflow
        result = await run_agent_workflow(message, state, deps)
        
        # Add assistant response
        assistant_message = Message.assistant(result.response)
        conversation = conversation.add_message(assistant_message)
        await conv_repo.update(conversation)
        
        # Convert suggestions to dicts
        suggestions = [
            {
                "title": s.title,
                "description": s.description,
                "relevance_score": s.relevance_score,
                "action_type": s.action_type,
            }
            for s in result.suggestions
        ]
        
        return result.response, conversation, suggestions


@dataclass
class PlanService:
    """Service for plan management.
    
    Handles plan creation, execution, and updates.
    """

    container: Container
    session: AsyncSession

    async def create_plan(
        self,
        user_id: UserId,
        conversation_id: ConversationId,
        goal_description: str,
        success_criteria: list[str],
        steps: list[dict],
    ) -> Plan:
        """Create a new plan.
        
        Args:
            user_id: The user's ID
            conversation_id: The conversation ID
            goal_description: Description of the goal
            success_criteria: List of success criteria
            steps: List of step dictionaries
            
        Returns:
            The created plan
        """
        plan_repo = self.container.get_plan_repository(self.session)
        
        goal = PlanGoal(
            description=goal_description,
            success_criteria=success_criteria,
            context={},
        )
        
        plan_steps = [
            PlanStep(
                description=step["description"],
                order=i,
                tool_required=step.get("tool_required"),
                dependencies=step.get("dependencies", []),
            )
            for i, step in enumerate(steps)
        ]
        
        plan = Plan.create(
            user_id=user_id,
            conversation_id=conversation_id,
            goal=goal,
            steps=plan_steps,
        )
        
        await plan_repo.save(plan)
        return plan

    async def execute_next_step(self, plan_id: PlanId) -> Plan:
        """Execute the next step in a plan.
        
        Args:
            plan_id: The plan ID
            
        Returns:
            The updated plan
        """
        plan_repo = self.container.get_plan_repository(self.session)
        
        plan = await plan_repo.get(plan_id)
        if not plan:
            raise ValueError(f"Plan not found: {plan_id}")
        
        if not plan.is_active:
            raise ValueError("Plan is not active")
        
        if plan.is_complete:
            raise ValueError("Plan is already complete")
        
        # Start the current step
        plan = plan.start_current_step()
        
        # In a real implementation, this would execute the step
        # For now, just complete it
        result = "Step executed successfully"
        plan = plan.complete_current_step(result)
        
        await plan_repo.update(plan)
        return plan


@dataclass
class UserService:
    """Service for user management.
    
    Handles user operations and preferences.
    """

    container: Container
    session: AsyncSession

    async def get_or_create_user(
        self,
        email: str,
        hashed_password: str,
    ) -> User:
        """Get an existing user or create a new one.
        
        Args:
            email: User email
            hashed_password: Hashed password
            
        Returns:
            The user
        """
        user_repo = self.container.get_user_repository(self.session)
        
        user = await user_repo.get_by_email(email)
        if user:
            return user
        
        user = User.create(
            email=email,
            hashed_password=hashed_password,
        )
        await user_repo.save(user)
        return user

    async def update_preferences(
        self,
        user_id: UserId,
        **preferences,
    ) -> User:
        """Update user preferences.
        
        Args:
            user_id: The user ID
            **preferences: Preference key-value pairs
            
        Returns:
            The updated user
        """
        user_repo = self.container.get_user_repository(self.session)
        
        user = await user_repo.get(user_id)
        if not user:
            raise ValueError(f"User not found: {user_id}")
        
        user = user.update_preferences(**preferences)
        await user_repo.update(user)
        return user
