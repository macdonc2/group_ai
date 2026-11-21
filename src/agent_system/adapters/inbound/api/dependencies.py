"""FastAPI dependency injection."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from starlette.requests import HTTPConnection
from sqlalchemy.ext.asyncio import AsyncSession

from agent_system.adapters.inbound.api.settings import SettingsDep, get_app_settings  # noqa: F401 - re-exported
from agent_system.adapters.outbound.persistence import Database
from agent_system.adapters.outbound.research.runner import ResearchRunner, get_runner
from agent_system.composition_root.container import Container, get_container
from agent_system.domain.ports import GoogleCalendarPort, KnowledgeGraphPort


# Global database instance (set by application factory)
_database: Database | None = None


def set_database(db: Database) -> None:
    """Set the global database instance."""
    global _database
    _database = db


def get_database() -> Database:
    """Get the database instance."""
    if _database is None:
        raise RuntimeError("Database not initialized. Call set_database first.")
    return _database


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a database session for dependency injection."""
    db = get_database()
    async with db.session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# Type alias for session dependency
SessionDep = Annotated[AsyncSession, Depends(get_session)]


# ---- The app's long-lived objects ------------------------------------------
#
# A route names what it needs as a parameter (`graph: KnowledgeGraphDep`) and FastAPI
# supplies it. The route's signature then says what it depends on, and a test can swap
# any of these with `app.dependency_overrides[get_knowledge_graph] = lambda: fake`.


async def get_app_container(connection: HTTPConnection) -> Container:
    """The container this app built at startup.

    `HTTPConnection` is what an HTTP request and a WebSocket have in common, so this
    works for both kinds of route. An app whose startup did not run (a test driving it
    without the lifespan) has no container, so it falls back to the shared `get_container()`.
    """
    container = getattr(connection.app.state, "container", None)
    return container if container is not None else await get_container()


ContainerDep = Annotated[Container, Depends(get_app_container)]


def get_optional_knowledge_graph(container: ContainerDep) -> KnowledgeGraphPort | None:
    """The graph store, or None when it is not available."""
    return container.knowledge_graph_adapter


def get_knowledge_graph(container: ContainerDep) -> KnowledgeGraphPort:
    """The graph store; the request ends with 503 when it is not available."""
    if not container.knowledge_graph_adapter:
        raise HTTPException(status_code=503, detail="Knowledge graph service not available")
    return container.knowledge_graph_adapter


def get_optional_google_calendar(container: ContainerDep) -> GoogleCalendarPort | None:
    """The Google Calendar adapter, or None when OAuth credentials are not configured."""
    return container.google_calendar_adapter


def get_google_calendar(container: ContainerDep) -> GoogleCalendarPort:
    """The Google Calendar adapter; the request ends with 503 when it is not configured."""
    if not container.google_calendar_adapter:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar integration is not configured",
        )
    return container.google_calendar_adapter


def get_research_runner() -> ResearchRunner:
    """The in-process Deep Research runner the app started."""
    return get_runner()


# "Optional" variants are for routes that carry on, or answer differently, without the
# adapter; the plain ones are for routes that cannot do anything without it.
KnowledgeGraphDep = Annotated[KnowledgeGraphPort, Depends(get_knowledge_graph)]
OptionalKnowledgeGraphDep = Annotated[KnowledgeGraphPort | None, Depends(get_optional_knowledge_graph)]
GoogleCalendarDep = Annotated[GoogleCalendarPort, Depends(get_google_calendar)]
OptionalGoogleCalendarDep = Annotated[GoogleCalendarPort | None, Depends(get_optional_google_calendar)]
ResearchRunnerDep = Annotated[ResearchRunner, Depends(get_research_runner)]


def user_api_key(user: object, settings: object) -> str | None:
    """The model API key to use for this user: the system key if there is one, else the
    user's own stored key, else None. The caller passes it to whatever builds a model; it is
    never written to the process environment, which every request shares."""
    system_key = getattr(settings, "openai_api_key", None)
    if system_key:
        return system_key
    if user is not None and user.has_api_key():
        from agent_system.domain.utils.encryption import get_api_key_encryption

        return get_api_key_encryption().decrypt(user.encrypted_openai_api_key)
    return None


async def get_current_user_id(
    token: "TokenData" = None,  # Injected by CurrentUserId dependency
) -> str:
    """Get the current authenticated user ID from JWT token."""
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return token.user_id


def _make_current_user_id_dependency():
    """Create the CurrentUserId dependency using the auth module."""
    from agent_system.adapters.inbound.api.auth import get_current_user_token, TokenData
    
    async def dependency(
        token: TokenData = Depends(get_current_user_token)
    ) -> str:
        return token.user_id
    
    return dependency


# Type alias for authenticated user ID from JWT - uses the same auth as /auth routes
CurrentUserId = Annotated[str, Depends(_make_current_user_id_dependency())]


async def get_current_user(
    current_user_id: CurrentUserId,
    session: SessionDep,
):
    """Get the current authenticated user entity.
    
    Args:
        current_user_id: The authenticated user's ID
        session: Database session
        
    Returns:
        The User entity
        
    Raises:
        HTTPException: If user not found
    """
    from agent_system.adapters.outbound.persistence import SQLAlchemyUserRepository
    from agent_system.domain.value_objects import UserId
    
    repo = SQLAlchemyUserRepository(session)
    user = await repo.get(UserId.from_string(current_user_id))
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    return user


async def require_conversation_access(
    conversation_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> str:
    """Verify user has access to the conversation.
    
    Args:
        conversation_id: The conversation ID to check
        current_user_id: The authenticated user ID
        session: Database session
        
    Returns:
        The conversation ID if access is granted
        
    Raises:
        HTTPException: If conversation not found or access denied
    """
    from agent_system.adapters.outbound.persistence import SQLAlchemyConversationRepository
    from agent_system.domain.value_objects import ConversationId
    
    repo = SQLAlchemyConversationRepository(session)
    conversation = await repo.get(ConversationId.from_string(conversation_id))
    
    # Someone else's conversation is reported as missing, so IDs can't be probed.
    if not conversation or str(conversation.user_id) != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    return conversation_id


async def require_plan_access(
    plan_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> str:
    """Verify user has access to the plan.
    
    Args:
        plan_id: The plan ID to check
        current_user_id: The authenticated user ID
        session: Database session
        
    Returns:
        The plan ID if access is granted
        
    Raises:
        HTTPException: If plan not found or access denied
    """
    from agent_system.adapters.outbound.persistence import SQLAlchemyPlanRepository
    from agent_system.domain.value_objects import PlanId
    
    repo = SQLAlchemyPlanRepository(session)
    plan = await repo.get(PlanId.from_string(plan_id))
    
    if not plan or str(plan.user_id) != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found",
        )

    return plan_id
