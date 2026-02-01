"""LLM adapter - PydanticAI OpenAI integration."""

from agent_system.adapters.outbound.llm.adapter import OpenAIAdapter
from agent_system.adapters.outbound.llm.agents import (
    create_coordinator_agent,
    create_streaming_coordinator_agent,
    create_intent_agent,
    create_knowledge_agent,
    create_planning_agent,
    create_react_planning_agent,
    create_step_execution_agent,
    create_streaming_synthesis_agent,
    create_synthesis_agent,
    create_tool_agent,
    get_coordinator_agent,
    get_intent_agent,
    get_knowledge_agent,
    get_planning_agent,
    get_tool_agent,
)
from agent_system.adapters.outbound.llm.schemas import (
    IntentAnalysis,
    KnowledgeExtraction,
    PlanSchema,
    PlanStepSchema,
    ReActPlanSchema,
    ResponseGeneration,
    StepExecution,
    StepSynthesis,
    ToolSelection,
)
from agent_system.adapters.outbound.llm.tools import (
    AVAILABLE_TOOLS,
    ToolResult,
    get_tools_description,
    web_search,
    get_user_profile,
    update_user_preference,
    remember_about_user,
    get_conversation_history,
    analyze_conversation_patterns,
    get_current_datetime,
    calculate,
    generate_random_fact,
    get_word_definition,
)
from agent_system.adapters.outbound.llm.title_generator import (
    generate_conversation_title,
)
from agent_system.adapters.outbound.llm.event_extractor import (
    create_event_extractor_agent,
    EventExtractionResult,
    ExtractedEventSchema,
    extract_events_from_text,
)
from agent_system.adapters.outbound.llm.group_summarizer import (
    create_group_summarizer_agent,
    create_social_matcher_agent,
    generate_group_summary,
    generate_social_suggestions,
    GroupSummaryResult,
    SocialMatchResult,
    SocialSuggestion,
    ThemeSummary,
)

__all__ = [
    # Adapter
    "OpenAIAdapter",
    # Agent factories
    "create_coordinator_agent",
    "create_streaming_coordinator_agent",
    "create_intent_agent",
    "create_planning_agent",
    "create_react_planning_agent",
    "create_step_execution_agent",
    "create_synthesis_agent",
    "create_streaming_synthesis_agent",
    "create_tool_agent",
    "create_knowledge_agent",
    # Agent getters (cached)
    "get_coordinator_agent",
    "get_intent_agent",
    "get_planning_agent",
    "get_tool_agent",
    "get_knowledge_agent",
    # Schemas
    "IntentAnalysis",
    "PlanSchema",
    "PlanStepSchema",
    "ReActPlanSchema",
    "StepExecution",
    "StepSynthesis",
    "ToolSelection",
    "ResponseGeneration",
    "KnowledgeExtraction",
    # Tools
    "AVAILABLE_TOOLS",
    "ToolResult",
    "get_tools_description",
    "web_search",
    "get_user_profile",
    "update_user_preference",
    "remember_about_user",
    "get_conversation_history",
    "analyze_conversation_patterns",
    "get_current_datetime",
    "calculate",
    "generate_random_fact",
    "get_word_definition",
    # Title generation
    "generate_conversation_title",
    # Event extraction
    "create_event_extractor_agent",
    "EventExtractionResult",
    "ExtractedEventSchema",
    "extract_events_from_text",
    # Group summarization
    "create_group_summarizer_agent",
    "create_social_matcher_agent",
    "generate_group_summary",
    "generate_social_suggestions",
    "GroupSummaryResult",
    "SocialMatchResult",
    "SocialSuggestion",
    "ThemeSummary",
]
