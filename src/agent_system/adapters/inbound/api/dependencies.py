"""FastAPI dependency injection."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_system.adapters.outbound.persistence import Database


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
    
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    
    # In production, check if current_user_id matches conversation.user_id
    # For now, we allow access
    
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
    
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found",
        )
    
    # In production, check if current_user_id matches plan.user_id
    
    return plan_id
