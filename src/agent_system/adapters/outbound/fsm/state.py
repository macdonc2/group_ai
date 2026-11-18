"""FSM state and context definitions."""

import asyncio
import time
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from pydantic_ai import ModelMessage

from agent_system.domain.entities import Conversation, Plan, User
from agent_system.domain.ports import (
    ConversationRepository,
    EmbeddingPort,
    GoogleCalendarPort,
    KnowledgeGraphPort,
    LLMPort,
    PlanRepository,
    UserRepository,
)
from agent_system.domain.value_objects import Intent, Message, Suggestion

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from agent_system.adapters.outbound.telemetry.trace import TurnTrace


# Type for event callback function
EventCallback = Callable[[str, str, str, dict | None], Coroutine[Any, Any, None]]


@dataclass(slots=True)
class AgentDependencies:
    """Everything one chat turn is handed: ports, configuration and per-request choices.

    This is the whole interface. Code reads these as plain attributes (`deps.persona`), so a
    misspelt name fails loudly instead of quietly using a default, and a new knob is added
    here as a field rather than attached to an instance from outside (`slots=True` makes
    setting an undeclared attribute an error).
    """

    # Ports (None where the app runs without one, and in tests that do not need it)
    llm_port: LLMPort | None
    user_repository: UserRepository | None
    conversation_repository: ConversationRepository | None
    plan_repository: PlanRepository | None
    knowledge_graph_port: KnowledgeGraphPort | None
    embedding_port: EmbeddingPort | None = None  # for semantic search
    google_calendar: GoogleCalendarPort | None = None  # None when OAuth is not configured

    # Opens a short-lived database session for a tool that needs one (the event tools).
    # A factory, not a session: most turns never call such a tool, so none is opened.
    session_factory: Callable[[], AbstractAsyncContextManager[Any]] | None = None

    # Configuration
    openai_api_key: str = ""
    default_model: str = "openai:gpt-5.2-2025-12-11"
    fallback_model: str = "openai:gpt-5-mini-2025-08-07"
    temperature: float = 0.7
    max_tokens: int = 4096

    # Per-request engine choice ("fsm" or "loop"); None uses the CHAT_ENGINE setting
    chat_engine: str | None = None

    # Limits for one turn; None uses CHAT_TURN_TIMEOUT_S / CHAT_TURN_MAX_LLM_CALLS
    turn_timeout_s: float | None = None
    turn_max_llm_calls: int | None = None

    # The model the loop engine runs on; None builds one from default_model and the API key.
    # Tests pass a scripted model here.
    chat_loop_model: "Model | str | None" = None

    # Optional wrestler persona key (see llm/personas.py); changes voice only
    persona: str | None = None
    
    # Event streaming callback (optional)
    event_callback: EventCallback | None = None

    # Turn trace (spans, decisions, retrievals, usage); None disables recording
    trace: "TurnTrace | None" = None

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
    input_embedding: list[float] | None = None  # embedded once in AnalyzeIntent, reused for retrieval
    
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
    
    # Set once a tool has put web text into this turn; write tools then refuse to run
    untrusted_seen: bool = False
    # Validated context for this turn (llm/context.py); created on first use by bundle_for()
    context_bundle: Any = None

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
