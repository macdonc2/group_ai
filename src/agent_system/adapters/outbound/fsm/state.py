"""FSM state and context definitions."""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from pydantic_ai import ModelMessage

from agent_system.domain.entities import Conversation, Plan, User
from agent_system.domain.value_objects import Intent, Message, Suggestion


# Type for event callback function
EventCallback = Callable[[str, str, str, dict | None], Coroutine[Any, Any, None]]


@dataclass
class AgentDependencies:
    """Dependencies injected into FSM nodes."""

    # Ports
    llm_port: Any  # LLMPort - using Any to avoid circular imports
    user_repository: Any  # UserRepository
    conversation_repository: Any  # ConversationRepository
    plan_repository: Any  # PlanRepository
    knowledge_graph_port: Any  # KnowledgeGraphPort (optional)
    embedding_port: Any = None  # EmbeddingPort - for semantic search (optional)

    # Configuration
    openai_api_key: str = ""
    default_model: str = "openai:gpt-5.2-2025-12-11"
    fallback_model: str = "openai:gpt-5-mini-2025-08-07"
    temperature: float = 0.7
    max_tokens: int = 4096

    # Optional wrestler persona key (see llm/personas.py); changes voice only
    persona: str | None = None
    
    # Event streaming callback (optional)
    event_callback: EventCallback | None = None

    # Turn trace (spans, decisions, retrievals, usage); None disables recording
    trace: Any = None  # TurnTrace

    async def emit_event(
        self,
        event_type: str,
        node_name: str,
        message: str,
        data: dict | None = None,
    ) -> None:
        """Emit an event to the callback if configured."""
        if self.trace is not None:
            self.trace.add_event(event_type, node_name, message, data)
        if self.event_callback:
            await self.event_callback(event_type, node_name, message, data)

    def decide(
        self,
        node: str,
        predicate: str,
        result: bool,
        next_node: str,
        **inputs: Any,
    ) -> bool:
        """Record a branch decision (the edge label in the predicate tree) and return `result`."""
        if self.trace is not None:
            self.trace.add_decision(node, predicate, result, next_node, inputs)
        return result

    def record_retrieval(self, source: str, query: str, hits: list[dict], **params: Any) -> None:
        if self.trace is not None:
            self.trace.add_retrieval(source, query, hits, **params)


@dataclass
class WorkflowState:
    """State maintained across FSM workflow execution."""

    # Current user and conversation context
    user: User
    conversation: Conversation
    
    # Current request
    user_input: str = ""
    
    # Extracted information
    intent: Intent | None = None
    entities: list[str] = field(default_factory=list)
    is_about_assistant: bool = False  # True if user asking about assistant capabilities
    
    # Plan management
    current_plan: Plan | None = None
    plan_needed: bool = False
    
    # Tool execution (determined by LLM during intent analysis)
    tool_name: str | None = None
    tool_input: str | None = None  # LLM-extracted input for the tool
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    tool_result: str | None = None
    
    # Response generation
    response: str = ""
    suggestions: list[Suggestion] = field(default_factory=list)
    
    # Agent message history for multi-turn
    coordinator_messages: list[ModelMessage] = field(default_factory=list)
    planner_messages: list[ModelMessage] = field(default_factory=list)
    
    # Workflow control
    requires_tool: bool = False
    is_complete: bool = False
    error: str | None = None
    
    # Group context (for group chats)
    group_context: dict[str, str] | None = None
    
    # ReAct-style step execution tracking
    react_mode: bool = False  # Whether to use ReAct-style reasoning
    step_results: list[dict[str, str]] = field(default_factory=list)  # List of {step, thought, observation}
    current_step_index: int = 0


@dataclass
class WorkflowResult:
    """Result returned from workflow execution."""

    response: str
    suggestions: list[Suggestion]
    plan_created: bool = False
    plan_updated: bool = False
    tools_used: list[str] = field(default_factory=list)
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    tool_result: str | None = None
    intents_detected: list[str] = field(default_factory=list)
    entities_extracted: list[str] = field(default_factory=list)
    error: str | None = None

    @classmethod
    def from_state(cls, state: WorkflowState) -> "WorkflowResult":
        """Create result from workflow state."""
        # Filter tool_arguments to only include JSON-serializable values
        # This removes injected dependencies (repositories, adapters, sessions)
        serializable_args = {}
        for key, value in state.tool_arguments.items():
            # Skip non-serializable objects (adapters, repositories, sessions)
            if key in ("knowledge_graph_port", "embedding_port", "user_repository", 
                       "conversation_repository", "session"):
                continue
            # Only include primitive types that are JSON-serializable
            if isinstance(value, (str, int, float, bool, list, dict, type(None))):
                serializable_args[key] = value
        
        return cls(
            response=state.response,
            suggestions=state.suggestions,
            plan_created=state.current_plan is not None and not state.conversation.active_plan_id,
            plan_updated=state.current_plan is not None and state.conversation.active_plan_id is not None,
            tools_used=[state.tool_name] if state.tool_name else [],
            tool_arguments=serializable_args,
            tool_result=state.tool_result,
            intents_detected=[state.intent.intent_type.value] if state.intent else [],
            entities_extracted=state.entities,
            error=state.error,
        )
