"""Agent interaction API routes."""

import asyncio
import logging
import os
import time
from collections.abc import AsyncGenerator

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from agent_system.adapters.inbound.api.auth import decode_access_token
from agent_system.adapters.inbound.api.dependencies import (
    CurrentUserId,
    SessionDep,
)
from agent_system.adapters.inbound.api.schemas import (
    AgentRequest,
    AgentResponse,
    StreamEvent,
    SuggestionRead,
)
from agent_system.adapters.outbound.persistence import (
    SQLAlchemyConversationRepository,
    SQLAlchemyPlanRepository,
    SQLAlchemyUserRepository,
)
from agent_system.domain.entities import Conversation, User
from agent_system.domain.value_objects import ConversationId, Message, UserId

router = APIRouter(prefix="/agent", tags=["agent"])
logger = logging.getLogger(__name__)


def setup_user_api_key(user: User, settings) -> str:
    """Set up the API key for the user, using their key if available.
    
    This sets the OPENAI_API_KEY environment variable which PydanticAI reads.
    
    Args:
        user: The current user
        settings: Application settings
        
    Returns:
        The API key being used
        
    Raises:
        ValueError: If no API key is available (neither user nor system key)
    """
    api_key: str | None = None
    
    # First try user's personal key
    if user.has_api_key():
        try:
            from agent_system.domain.utils.encryption import get_api_key_encryption
            encryption = get_api_key_encryption()
            decrypted_key = encryption.decrypt(user.encrypted_openai_api_key)
            api_key = decrypted_key
            logger.debug(f"Using user's personal API key for {user.email}")
        except Exception as e:
            logger.warning(f"Failed to decrypt user API key: {e}")
            api_key = None
    
    # Fall back to system key if user key not available
    if not api_key and settings.openai_api_key:
        api_key = settings.openai_api_key
        logger.debug(f"User {user.email} has no valid API key, using system default")
    
    # Raise error if no key available
    if not api_key:
        raise ValueError(
            "No OpenAI API key available. Please configure your API key in Settings."
        )
    
    # Set environment variable for PydanticAI
    os.environ["OPENAI_API_KEY"] = api_key
    
    return api_key


@router.post("/chat", response_model=AgentResponse)
async def chat_with_agent(
    data: AgentRequest,
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> AgentResponse:
    """Send a message to the agent and get a response.
    
    This endpoint handles the main agent interaction flow:
    1. Get or create conversation
    2. Add user message
    3. Run the FSM agent workflow with real LLM calls
    4. Return the response with suggestions
    """
    from agent_system.adapters.outbound.fsm import (
        AgentDependencies,
        WorkflowState,
        run_agent_workflow,
    )
    from agent_system.composition_root.config import get_settings
    
    settings = get_settings()
    
    user_repo = SQLAlchemyUserRepository(session)
    conv_repo = SQLAlchemyConversationRepository(session)
    plan_repo = SQLAlchemyPlanRepository(session)
    
    # Get user (or create a test user for development)
    user = await user_repo.get(UserId.from_string(current_user_id))
    if not user:
        # Create a test user for development
        user = User.create(
            email="test@example.com",
            hashed_password="test",
        )
        user = user.model_copy(update={"id": UserId.from_string(current_user_id)})
        await user_repo.save(user)
    
    # Set up user's API key early (needed for title generation and workflow)
    api_key = setup_user_api_key(user, settings)
    
    # Get or create conversation
    is_new_conversation = False
    if data.conversation_id:
        conversation = await conv_repo.get(
            ConversationId.from_string(data.conversation_id)
        )
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
    else:
        conversation = Conversation.create(user_id=user.id)
        await conv_repo.save(conversation)
        is_new_conversation = True
    
    # Add user message to conversation
    user_message = Message.user(data.message)
    conversation = conversation.add_message(user_message)
    
    # Generate title for new conversations (using user's API key)
    if is_new_conversation:
        from agent_system.adapters.outbound.llm import generate_conversation_title
        try:
            title = await generate_conversation_title(data.message, api_key=api_key)
            conversation = conversation.update_metadata(title=title)
        except Exception:
            # Use first few words as fallback
            words = data.message.split()[:5]
            conversation = conversation.update_metadata(title=" ".join(words))
    
    # Get active plan if any
    current_plan = None
    if conversation.active_plan_id:
        current_plan = await plan_repo.get(conversation.active_plan_id)
    
    # Create workflow state
    state = WorkflowState(
        user=user,
        conversation=conversation,
        current_plan=current_plan,
    )
    
    # Get knowledge graph from container (if available)
    from agent_system.composition_root.container import get_container
    container = await get_container()
    
    # Create embedding adapter using user's API key if not available from container
    embedding_port = container.embedding_adapter
    if embedding_port is None and api_key:
        from agent_system.adapters.outbound.embedding import OpenAIEmbeddingAdapter
        embedding_port = OpenAIEmbeddingAdapter(api_key=api_key)
    
    # Create dependencies for the workflow
    deps = AgentDependencies(
        llm_port=None,  # Using PydanticAI agents directly
        user_repository=user_repo,
        conversation_repository=conv_repo,
        plan_repository=plan_repo,
        knowledge_graph_port=container.knowledge_graph_adapter,
        embedding_port=embedding_port,
        openai_api_key=api_key,
        default_model=settings.default_model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
    )
    
    # Run the FSM workflow
    try:
        result = await run_agent_workflow(data.message, state, deps)
        
        # Add assistant response to conversation (include tool calls for history)
        from agent_system.domain.value_objects.message import ToolCall
        tool_calls = [
            ToolCall(tool_name=tool, arguments=result.tool_arguments, result=result.tool_result)
            for tool in result.tools_used
        ]
        assistant_message = Message.assistant(result.response, tool_calls=tool_calls)
        conversation = conversation.add_message(assistant_message)
        await conv_repo.update(conversation)
        
        # Convert suggestions
        suggestions = [
            SuggestionRead(
                title=s.title,
                description=s.description,
                relevance_score=s.relevance_score,
                action_type=s.action_type,
            )
            for s in result.suggestions
        ]
        
        return AgentResponse(
            response=result.response,
            conversation_id=str(conversation.id),
            suggestions=suggestions,
            plan_created=result.plan_created,
            plan_updated=result.plan_updated,
            tools_used=result.tools_used,
        )
        
    except Exception as e:
        # Fallback response on error
        error_response = f"I encountered an issue processing your request: {str(e)[:100]}. Please try again."
        
        assistant_message = Message.assistant(error_response)
        conversation = conversation.add_message(assistant_message)
        await conv_repo.update(conversation)
        
        return AgentResponse(
            response=error_response,
            conversation_id=str(conversation.id),
            suggestions=[
                SuggestionRead(
                    title="Try again",
                    description="Please rephrase your request",
                    relevance_score=0.8,
                    action_type="retry",
                )
            ],
            plan_created=False,
            plan_updated=False,
            tools_used=[],
        )


@router.get("/chat/stream")
async def chat_with_agent_stream(
    message: str = Query(..., description="User message"),
    conversation_id: str | None = Query(None, description="Conversation ID"),
    token: str | None = Query(None, description="Auth token for SSE (EventSource can't send headers)"),
    session: SessionDep = None,
) -> StreamingResponse:
    """Stream agent responses with real-time FSM trace events.
    
    This endpoint uses Server-Sent Events to stream:
    - node_start: When a workflow node begins execution
    - node_complete: When a workflow node completes
    - tool_result: When a tool returns a result
    - response: Final response with suggestions
    - error: If an error occurs
    
    Note: Uses token query param because EventSource API cannot send headers.
    """
    # Validate token from query param (EventSource can't send Authorization header)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token required",
        )
    
    try:
        token_data = decode_access_token(token)
        current_user_id = token_data.user_id
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    
    from agent_system.adapters.outbound.fsm import (
        AgentDependencies,
        WorkflowState,
        run_agent_workflow,
    )
    from agent_system.composition_root.config import get_settings
    
    settings = get_settings()
    
    user_repo = SQLAlchemyUserRepository(session)
    conv_repo = SQLAlchemyConversationRepository(session)
    plan_repo = SQLAlchemyPlanRepository(session)
    
    # Event queue for streaming
    event_queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
    
    async def event_callback(
        event_type: str,
        node_name: str,
        msg: str,
        data: dict | None,
    ) -> None:
        """Callback to emit events to the queue."""
        event = StreamEvent(
            event_type=event_type,
            node_name=node_name,
            message=msg,
            data=data,
            timestamp=time.time(),
        )
        await event_queue.put(event)
    
    async def run_workflow() -> None:
        """Run the workflow and push events to queue."""
        try:
            # Get user
            user = await user_repo.get(UserId.from_string(current_user_id))
            if not user:
                user = User.create(email="test@example.com", hashed_password="test")
                user = user.model_copy(update={"id": UserId.from_string(current_user_id)})
                await user_repo.save(user)
            
            # Set up user's API key early (needed for title generation and workflow)
            api_key = setup_user_api_key(user, settings)
            
            # Get or create conversation
            if conversation_id:
                conversation = await conv_repo.get(ConversationId.from_string(conversation_id))
                if not conversation:
                    await event_queue.put(StreamEvent(
                        event_type="error",
                        node_name=None,
                        message="Conversation not found",
                        data=None,
                        timestamp=time.time(),
                    ))
                    await event_queue.put(None)
                    return
            else:
                conversation = Conversation.create(user_id=user.id)
                await conv_repo.save(conversation)
                
                # Generate title for new conversation (using user's API key)
                from agent_system.adapters.outbound.llm import generate_conversation_title
                try:
                    title = await generate_conversation_title(message, api_key=api_key)
                    conversation = conversation.update_metadata(title=title)
                except Exception:
                    words = message.split()[:5]
                    conversation = conversation.update_metadata(title=" ".join(words))
            
            # Add user message
            user_message = Message.user(message)
            conversation = conversation.add_message(user_message)
            
            # Get active plan
            current_plan = None
            if conversation.active_plan_id:
                current_plan = await plan_repo.get(conversation.active_plan_id)
            
            # Create workflow state
            state = WorkflowState(
                user=user,
                conversation=conversation,
                current_plan=current_plan,
            )
            
            # Get knowledge graph from container (if available)
            from agent_system.composition_root.container import get_container
            container = await get_container()
            
            # Create embedding adapter using user's API key if not available from container
            embedding_port = container.embedding_adapter
            if embedding_port is None and api_key:
                from agent_system.adapters.outbound.embedding import OpenAIEmbeddingAdapter
                embedding_port = OpenAIEmbeddingAdapter(api_key=api_key)
            
            # Create dependencies with event callback
            deps = AgentDependencies(
                llm_port=None,
                user_repository=user_repo,
                conversation_repository=conv_repo,
                plan_repository=plan_repo,
                knowledge_graph_port=container.knowledge_graph_adapter,
                embedding_port=embedding_port,
                openai_api_key=api_key,
                default_model=settings.default_model,
                temperature=settings.temperature,
                max_tokens=settings.max_tokens,
                event_callback=event_callback,
            )
            
            # Run workflow
            result = await run_agent_workflow(message, state, deps)
            
            # Save conversation with response (include tool calls for history)
            from agent_system.domain.value_objects.message import ToolCall
            tool_calls = [
                ToolCall(tool_name=tool, arguments=result.tool_arguments, result=result.tool_result)
                for tool in result.tools_used
            ]
            assistant_message = Message.assistant(result.response, tool_calls=tool_calls)
            conversation = conversation.add_message(assistant_message)
            await conv_repo.update(conversation)
            
            # Send final response event with full response and suggestions
            await event_queue.put(StreamEvent(
                event_type="response",
                node_name=None,
                message="Response complete",
                data={
                    "response": result.response,
                    "conversation_id": str(conversation.id),
                    "suggestions": [
                        {
                            "title": s.title,
                            "description": s.description,
                            "relevance_score": s.relevance_score,
                            "action_type": s.action_type,
                        }
                        for s in result.suggestions
                    ],
                    "plan_created": result.plan_created,
                    "plan_updated": result.plan_updated,
                    "tools_used": result.tools_used,
                },
                timestamp=time.time(),
            ))
            
        except Exception as e:
            await event_queue.put(StreamEvent(
                event_type="error",
                node_name=None,
                message=str(e)[:200],
                data=None,
                timestamp=time.time(),
            ))
        finally:
            # Signal end of stream
            await event_queue.put(None)
    
    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events from queue."""
        # Start workflow in background
        task = asyncio.create_task(run_workflow())
        
        try:
            while True:
                event = await event_queue.get()
                if event is None:
                    break
                yield event.to_sse()
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/stream")
async def chat_with_agent_stream_post(
    data: AgentRequest,
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> StreamingResponse:
    """Stream agent responses (POST version for request body support)."""
    from fastapi import Request
    from starlette.responses import RedirectResponse
    
    # Redirect to GET with query params for SSE compatibility
    # Most browsers/EventSource only support GET for SSE
    params = f"message={data.message}"
    if data.conversation_id:
        params += f"&conversation_id={data.conversation_id}"
    
    return await chat_with_agent_stream(
        message=data.message,
        conversation_id=data.conversation_id,
        current_user_id=current_user_id,
        session=session,
    )
