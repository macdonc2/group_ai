"""Tools API routes for direct tool access."""

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from agent_system.adapters.inbound.api.dependencies import (
    CurrentUserId,
    SessionDep,
)
from agent_system.adapters.outbound.persistence import (
    SQLAlchemyConversationRepository,
    SQLAlchemyUserRepository,
)
from agent_system.adapters.outbound.llm.tools import (
    AVAILABLE_TOOLS,
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

router = APIRouter(prefix="/tools", tags=["tools"])


class ToolInfo(BaseModel):
    """Information about an available tool."""

    name: str
    description: str
    parameters: dict[str, str]


class ToolExecutionRequest(BaseModel):
    """Request to execute a tool."""

    tool_name: str
    arguments: dict[str, Any] = {}


class ToolExecutionResponse(BaseModel):
    """Response from tool execution."""

    success: bool
    data: Any | None
    message: str


@router.get("", response_model=list[ToolInfo])
async def list_tools() -> list[ToolInfo]:
    """List all available tools and their descriptions."""
    tools = []
    for name, info in AVAILABLE_TOOLS.items():
        tools.append(
            ToolInfo(
                name=name,
                description=info["description"],
                parameters=info["parameters"],
            )
        )
    return tools


@router.post("/execute", response_model=ToolExecutionResponse)
async def execute_tool(
    request: ToolExecutionRequest,
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> ToolExecutionResponse:
    """Execute a tool directly.
    
    Available tools:
    - web_search: Search the web (args: query, num_results)
    - get_user_profile: Get your profile (no args needed)
    - update_user_preference: Update a preference (args: preference_name, preference_value)
    - remember_about_user: Store a learned pattern (args: pattern_type, description)
    - get_conversation_history: Get recent conversations (args: limit)
    - analyze_conversation_patterns: Analyze your usage patterns (no args needed)
    - get_current_datetime: Get current date/time (no args needed)
    - calculate: Evaluate a math expression (args: expression)
    - random_fact: Get a random fact (no args needed)
    - define_word: Look up a word definition (args: word)
    """
    tool_name = request.tool_name
    args = request.arguments.copy()
    
    if tool_name not in AVAILABLE_TOOLS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown tool: {tool_name}. Available tools: {list(AVAILABLE_TOOLS.keys())}",
        )
    
    tool_info = AVAILABLE_TOOLS[tool_name]
    tool_func = tool_info["function"]
    
    # Add user_id for user-specific tools
    if tool_name in ["get_user_profile", "update_user_preference", "remember_about_user", 
                     "get_conversation_history", "analyze_conversation_patterns"]:
        args["user_id"] = current_user_id
    
    # Add repositories if needed
    if tool_info.get("requires_repos"):
        if "user_repository" in tool_func.__code__.co_varnames:
            args["user_repository"] = SQLAlchemyUserRepository(session)
        if "conversation_repository" in tool_func.__code__.co_varnames:
            args["conversation_repository"] = SQLAlchemyConversationRepository(session)
    
    try:
        result = await tool_func(**args)
        return ToolExecutionResponse(
            success=result.success,
            data=result.data,
            message=result.message,
        )
    except Exception as e:
        return ToolExecutionResponse(
            success=False,
            data=None,
            message=f"Error executing tool: {str(e)}",
        )


# Convenience endpoints for common tools

@router.get("/search", response_model=ToolExecutionResponse)
async def search_web(query: str, num_results: int = 5) -> ToolExecutionResponse:
    """Search the web for information."""
    result = await web_search(query, num_results)
    return ToolExecutionResponse(
        success=result.success,
        data=result.data,
        message=result.message,
    )


@router.get("/datetime", response_model=ToolExecutionResponse)
async def get_datetime() -> ToolExecutionResponse:
    """Get the current date and time."""
    result = await get_current_datetime()
    return ToolExecutionResponse(
        success=result.success,
        data=result.data,
        message=result.message,
    )


@router.get("/calculate", response_model=ToolExecutionResponse)
async def calc(expression: str) -> ToolExecutionResponse:
    """Calculate a mathematical expression."""
    result = await calculate(expression)
    return ToolExecutionResponse(
        success=result.success,
        data=result.data,
        message=result.message,
    )


@router.get("/fact", response_model=ToolExecutionResponse)
async def random_fact() -> ToolExecutionResponse:
    """Get a random interesting fact."""
    result = await generate_random_fact()
    return ToolExecutionResponse(
        success=result.success,
        data=result.data,
        message=result.message,
    )


@router.get("/define/{word}", response_model=ToolExecutionResponse)
async def define(word: str) -> ToolExecutionResponse:
    """Look up a word's definition."""
    result = await get_word_definition(word)
    return ToolExecutionResponse(
        success=result.success,
        data=result.data,
        message=result.message,
    )


@router.get("/profile", response_model=ToolExecutionResponse)
async def get_my_profile(
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> ToolExecutionResponse:
    """Get your user profile and preferences."""
    user_repo = SQLAlchemyUserRepository(session)
    result = await get_user_profile(current_user_id, user_repo)
    return ToolExecutionResponse(
        success=result.success,
        data=result.data,
        message=result.message,
    )


@router.get("/history", response_model=ToolExecutionResponse)
async def get_my_history(
    current_user_id: CurrentUserId,
    session: SessionDep,
    limit: int = 10,
) -> ToolExecutionResponse:
    """Get your conversation history."""
    conv_repo = SQLAlchemyConversationRepository(session)
    result = await get_conversation_history(current_user_id, conv_repo, limit)
    return ToolExecutionResponse(
        success=result.success,
        data=result.data,
        message=result.message,
    )


@router.get("/analytics", response_model=ToolExecutionResponse)
async def get_my_analytics(
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> ToolExecutionResponse:
    """Get analytics about your conversation patterns."""
    conv_repo = SQLAlchemyConversationRepository(session)
    result = await analyze_conversation_patterns(current_user_id, conv_repo)
    return ToolExecutionResponse(
        success=result.success,
        data=result.data,
        message=result.message,
    )
