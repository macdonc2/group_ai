"""Authentication routes."""

import logging

from fastapi import APIRouter, HTTPException, status

from agent_system.adapters.inbound.api.auth import (
    CurrentUserToken,
    RequireSuperuser,
    create_access_token,
    hash_password,
    TokenData,
    verify_password,
)
from agent_system.adapters.inbound.api.dependencies import SessionDep
from pydantic import BaseModel

from agent_system.adapters.inbound.api.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    UserRead,
)
from agent_system.adapters.outbound.persistence.repositories import SQLAlchemyUserRepository
from agent_system.domain.entities import User
from agent_system.domain.utils.encryption import get_api_key_encryption
from agent_system.domain.value_objects import UserId


class APIKeySetRequest(BaseModel):
    """Request to set an API key."""
    api_key: str


class APIKeyStatusResponse(BaseModel):
    """Response showing API key status."""
    has_api_key: bool
    message: str


class TimezoneSetRequest(BaseModel):
    """Request to set user timezone."""
    timezone: str  # e.g., "America/Chicago", "Europe/London", "UTC"


class TimezoneResponse(BaseModel):
    """Response showing timezone status."""
    timezone: str
    message: str

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


@router.post("/login", response_model=LoginResponse)
async def login(
    data: LoginRequest,
    session: SessionDep,
):
    """Authenticate a user and return an access token."""
    user_repo = SQLAlchemyUserRepository(session)
    
    # Find user by email
    user = await user_repo.get_by_email(data.email)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    
    # Verify password
    if not verify_password(data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    
    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )
    
    # Check if user is verified (approved)
    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is not verified. Contact an administrator.",
        )
    
    # Create access token
    token_data = TokenData(
        user_id=str(user.id),
        email=user.email,
        is_superuser=user.is_superuser,
    )
    access_token = create_access_token(token_data)
    
    logger.info(f"User logged in: {user.email}")
    
    return LoginResponse(
        access_token=access_token,
        user=UserRead(
            id=str(user.id),
            email=user.email,
            is_active=user.is_active,
            is_verified=user.is_verified,
            is_superuser=user.is_superuser,
            timezone=user.timezone,
            created_at=user.created_at,
        ),
    )


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register_user(
    data: RegisterRequest,
    admin: RequireSuperuser,
    session: SessionDep,
):
    """Register a new user (superuser only).
    
    New users are automatically verified/approved when created by an admin.
    """
    user_repo = SQLAlchemyUserRepository(session)
    
    # Check if email already exists
    existing = await user_repo.get_by_email(data.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    
    # Create user with hashed password
    hashed = hash_password(data.password)
    user = User.create(
        email=data.email,
        hashed_password=hashed,
        is_superuser=data.is_superuser,
    )
    # Automatically verify users created by admin
    user = user.verify()
    
    await user_repo.save(user)
    await session.commit()
    
    logger.info(f"New user registered by {admin.email}: {user.email}")
    
    return UserRead(
        id=str(user.id),
        email=user.email,
        is_active=user.is_active,
        is_verified=user.is_verified,
        is_superuser=user.is_superuser,
        timezone=user.timezone,
        created_at=user.created_at,
    )


@router.get("/me", response_model=UserRead)
async def get_current_user(
    token: CurrentUserToken,
    session: SessionDep,
):
    """Get the currently authenticated user."""
    user_repo = SQLAlchemyUserRepository(session)
    
    user = await user_repo.get(UserId.from_string(token.user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    return UserRead(
        id=str(user.id),
        email=user.email,
        is_active=user.is_active,
        is_verified=user.is_verified,
        is_superuser=user.is_superuser,
        timezone=user.timezone,
        created_at=user.created_at,
    )


@router.post("/change-password")
async def change_password(
    data: ChangePasswordRequest,
    token: CurrentUserToken,
    session: SessionDep,
):
    """Change the current user's password."""
    user_repo = SQLAlchemyUserRepository(session)
    
    user = await user_repo.get(UserId.from_string(token.user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # Verify current password
    if not verify_password(data.current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )
    
    # Update password
    user.hashed_password = hash_password(data.new_password)
    await user_repo.update(user)
    await session.commit()
    
    logger.info(f"User changed password: {user.email}")
    
    return {"message": "Password changed successfully"}


@router.get("/users", response_model=list[UserRead])
async def list_users(
    admin: RequireSuperuser,
    session: SessionDep,
):
    """List all users (superuser only)."""
    user_repo = SQLAlchemyUserRepository(session)
    
    users = await user_repo.list_active(limit=100)
    
    return [
        UserRead(
            id=str(u.id),
            email=u.email,
            is_active=u.is_active,
            is_verified=u.is_verified,
            is_superuser=u.is_superuser,
            timezone=u.timezone,
            created_at=u.created_at,
        )
        for u in users
    ]


class UserSearchResult(BaseModel):
    """Simplified user info for search results."""
    id: str
    email: str
    is_active: bool
    is_verified: bool


@router.get("/users/search", response_model=list[UserSearchResult])
async def search_users(
    current_user: CurrentUserToken,
    session: SessionDep,
):
    """Search users for adding to groups (any authenticated user)."""
    user_repo = SQLAlchemyUserRepository(session)
    
    # Get all active users
    users = await user_repo.list_active(limit=100)
    
    return [
        UserSearchResult(
            id=str(u.id),
            email=u.email,
            is_active=u.is_active,
            is_verified=u.is_verified,
        )
        for u in users
    ]


@router.post("/users/{user_id}/verify", response_model=UserRead)
async def verify_user(
    user_id: str,
    admin: RequireSuperuser,
    session: SessionDep,
):
    """Verify/approve a user (superuser only)."""
    user_repo = SQLAlchemyUserRepository(session)
    
    user = await user_repo.get(UserId.from_string(user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    user = user.verify()
    await user_repo.update(user)
    await session.commit()
    
    logger.info(f"User verified by {admin.email}: {user.email}")
    
    return UserRead(
        id=str(user.id),
        email=user.email,
        is_active=user.is_active,
        is_verified=user.is_verified,
        is_superuser=user.is_superuser,
        timezone=user.timezone,
        created_at=user.created_at,
    )


@router.post("/users/{user_id}/deactivate", response_model=UserRead)
async def deactivate_user(
    user_id: str,
    admin: RequireSuperuser,
    session: SessionDep,
):
    """Deactivate a user (superuser only)."""
    user_repo = SQLAlchemyUserRepository(session)
    
    user = await user_repo.get(UserId.from_string(user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # Prevent deactivating yourself
    if str(user.id) == admin.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account",
        )
    
    user = user.deactivate()
    await user_repo.update(user)
    await session.commit()
    
    logger.info(f"User deactivated by {admin.email}: {user.email}")
    
    return UserRead(
        id=str(user.id),
        email=user.email,
        is_active=user.is_active,
        is_verified=user.is_verified,
        is_superuser=user.is_superuser,
        timezone=user.timezone,
        created_at=user.created_at,
    )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    admin: RequireSuperuser,
    session: SessionDep,
):
    """Delete a user (superuser only)."""
    user_repo = SQLAlchemyUserRepository(session)
    
    user = await user_repo.get(UserId.from_string(user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # Prevent deleting yourself
    if str(user.id) == admin.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )
    
    await user_repo.delete(user.id)
    await session.commit()
    
    logger.info(f"User deleted by {admin.email}: {user.email}")


@router.post("/bootstrap", response_model=LoginResponse)
async def bootstrap_admin(
    data: RegisterRequest,
    session: SessionDep,
):
    """Bootstrap the first admin user.
    
    This endpoint only works when no users exist in the system.
    It creates a verified superuser and returns a login token.
    """
    user_repo = SQLAlchemyUserRepository(session)
    
    # Check if any users exist
    existing_users = await user_repo.list_active(limit=1)
    if existing_users:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bootstrap not allowed - users already exist. Use /login instead.",
        )
    
    # Create the first admin user
    hashed = hash_password(data.password)
    user = User.create(
        email=data.email,
        hashed_password=hashed,
        is_superuser=True,  # First user is always superuser
    )
    user = user.verify()  # Auto-verify
    
    await user_repo.save(user)
    await session.commit()
    
    # Create access token
    token_data = TokenData(
        user_id=str(user.id),
        email=user.email,
        is_superuser=user.is_superuser,
    )
    access_token = create_access_token(token_data)
    
    logger.info(f"Bootstrap: Created first admin user: {user.email}")
    
    return LoginResponse(
        access_token=access_token,
        user=UserRead(
            id=str(user.id),
            email=user.email,
            is_active=user.is_active,
            is_verified=user.is_verified,
            is_superuser=user.is_superuser,
            timezone=user.timezone,
            created_at=user.created_at,
        ),
    )


# ==================== API Key Management ====================


@router.put("/me/api-key", response_model=APIKeyStatusResponse)
async def set_api_key(
    data: APIKeySetRequest,
    token: CurrentUserToken,
    session: SessionDep,
):
    """Set or update the user's OpenAI API key.
    
    The key is encrypted before storage and never returned.
    """
    user_repo = SQLAlchemyUserRepository(session)
    
    user = await user_repo.get(UserId.from_string(token.user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # Validate API key format (basic check)
    if not data.api_key.startswith("sk-"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid API key format. OpenAI keys start with 'sk-'",
        )
    
    # Encrypt and store the API key
    encryption = get_api_key_encryption()
    encrypted_key = encryption.encrypt(data.api_key)
    
    user = user.set_encrypted_api_key(encrypted_key)
    await user_repo.update(user)
    await session.commit()
    
    logger.info(f"User set API key: {user.email}")
    
    return APIKeyStatusResponse(
        has_api_key=True,
        message="API key saved successfully",
    )


@router.get("/me/api-key/status", response_model=APIKeyStatusResponse)
async def get_api_key_status(
    token: CurrentUserToken,
    session: SessionDep,
):
    """Check if the user has an API key configured.
    
    Does not return the actual key for security.
    """
    user_repo = SQLAlchemyUserRepository(session)
    
    user = await user_repo.get(UserId.from_string(token.user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    has_key = user.has_api_key()
    
    return APIKeyStatusResponse(
        has_api_key=has_key,
        message="API key is configured" if has_key else "No API key configured - using system default",
    )


@router.delete("/me/api-key", response_model=APIKeyStatusResponse)
async def remove_api_key(
    token: CurrentUserToken,
    session: SessionDep,
):
    """Remove the user's API key (will fall back to system default)."""
    user_repo = SQLAlchemyUserRepository(session)
    
    user = await user_repo.get(UserId.from_string(token.user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    user = user.set_encrypted_api_key(None)
    await user_repo.update(user)
    await session.commit()
    
    logger.info(f"User removed API key: {user.email}")
    
    return APIKeyStatusResponse(
        has_api_key=False,
        message="API key removed - using system default",
    )


# ==================== Timezone Management ====================


@router.put("/me/timezone", response_model=TimezoneResponse)
async def set_timezone(
    data: TimezoneSetRequest,
    token: CurrentUserToken,
    session: SessionDep,
):
    """Set the user's timezone.
    
    Common timezone values:
    - America/New_York (Eastern)
    - America/Chicago (Central)
    - America/Denver (Mountain)
    - America/Los_Angeles (Pacific)
    - Europe/London
    - Europe/Paris
    - Asia/Tokyo
    - UTC
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    
    user_repo = SQLAlchemyUserRepository(session)
    
    user = await user_repo.get(UserId.from_string(token.user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # Validate timezone
    try:
        ZoneInfo(data.timezone)
    except ZoneInfoNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid timezone: {data.timezone}. Use IANA timezone names like 'America/Chicago'",
        )
    
    user = user.set_timezone(data.timezone)
    await user_repo.update(user)
    await session.commit()
    
    logger.info(f"User set timezone: {user.email} -> {data.timezone}")
    
    return TimezoneResponse(
        timezone=user.timezone,
        message=f"Timezone set to {user.timezone}",
    )


@router.get("/me/timezone", response_model=TimezoneResponse)
async def get_timezone(
    token: CurrentUserToken,
    session: SessionDep,
):
    """Get the user's current timezone setting."""
    user_repo = SQLAlchemyUserRepository(session)
    
    user = await user_repo.get(UserId.from_string(token.user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    return TimezoneResponse(
        timezone=user.timezone,
        message=f"Current timezone: {user.timezone}",
    )
