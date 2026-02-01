"""Google Calendar OAuth and sync API routes."""

import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from agent_system.adapters.inbound.api.dependencies import (
    CurrentUserId,
    SessionDep,
)
from agent_system.adapters.outbound.persistence import SQLAlchemyUserRepository
from agent_system.composition_root.container import get_container
from agent_system.domain.utils.encryption import get_api_key_encryption
from agent_system.domain.value_objects import UserId

router = APIRouter(prefix="/calendar", tags=["calendar"])
logger = logging.getLogger(__name__)

# In-memory state storage for OAuth flow (in production, use Redis)
# Maps state token -> user_id for CSRF protection
_oauth_states: dict[str, str] = {}


class CalendarStatusResponse(BaseModel):
    """Response showing Google Calendar connection status."""

    connected: bool
    email: str | None = None
    selected_calendar_id: str | None = None
    calendar_enabled: bool = False
    sync_confirmed_only: bool = False


class CalendarConnectResponse(BaseModel):
    """Response with OAuth authorization URL."""

    authorization_url: str


class CalendarSettingsUpdate(BaseModel):
    """Request to update calendar settings."""

    selected_calendar_id: str | None = None
    sync_confirmed_only: bool | None = None
    calendar_enabled: bool | None = None


class GoogleCalendarInfo(BaseModel):
    """Information about a Google Calendar."""

    id: str
    name: str
    is_primary: bool
    access_role: str


@router.get("/status", response_model=CalendarStatusResponse)
async def get_calendar_status(
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> CalendarStatusResponse:
    """Get the current Google Calendar connection status."""
    user_repo = SQLAlchemyUserRepository(session)
    user = await user_repo.get(UserId.from_string(current_user_id))

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    return CalendarStatusResponse(
        connected=user.has_google_calendar_connected(),
        email=user.google_calendar_email,
        selected_calendar_id=user.preferences.google_calendar_id,
        calendar_enabled=user.preferences.google_calendar_enabled,
        sync_confirmed_only=user.preferences.calendar_sync_confirmed_only,
    )


@router.post("/connect", response_model=CalendarConnectResponse)
async def connect_google_calendar(
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> CalendarConnectResponse:
    """Start the Google Calendar OAuth flow.

    Returns an authorization URL to redirect the user to.
    """
    container = await get_container()

    if not container.google_calendar_adapter:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar integration is not configured",
        )

    # Generate state token for CSRF protection
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = current_user_id

    # Get authorization URL
    auth_url = container.google_calendar_adapter.get_authorization_url(state)

    logger.info(f"Starting OAuth flow for user {current_user_id}")
    logger.info(f"Generated authorization URL: {auth_url[:100]}...")
    return CalendarConnectResponse(authorization_url=auth_url)


@router.get("/callback")
async def oauth_callback(
    code: Annotated[str, Query(description="Authorization code from Google")],
    state: Annotated[str, Query(description="State token for CSRF protection")],
    session: SessionDep,
) -> RedirectResponse:
    """Handle the OAuth callback from Google.

    Exchanges the authorization code for tokens and stores them.
    Redirects back to the frontend settings page.
    """
    # Verify state token
    user_id = _oauth_states.pop(state, None)
    if not user_id:
        logger.warning(f"Invalid OAuth state token: {state}")
        return RedirectResponse(
            url="/settings?calendar_error=invalid_state", status_code=302
        )

    container = await get_container()
    if not container.google_calendar_adapter:
        return RedirectResponse(
            url="/settings?calendar_error=not_configured", status_code=302
        )

    try:
        # Exchange code for tokens
        tokens = await container.google_calendar_adapter.exchange_code_for_tokens(code)

        # Get user info (email)
        user_info = await container.google_calendar_adapter.get_user_info(
            tokens.access_token
        )

        # Encrypt and store refresh token
        encryption = get_api_key_encryption()
        encrypted_token = encryption.encrypt(tokens.refresh_token)

        # Update user
        user_repo = SQLAlchemyUserRepository(session)
        user = await user_repo.get(UserId.from_string(user_id))

        if not user:
            return RedirectResponse(
                url="/settings?calendar_error=user_not_found", status_code=302
            )

        updated_user = user.connect_google_calendar(
            encrypted_refresh_token=encrypted_token,
            email=user_info.email,
        )
        await user_repo.update(updated_user)
        await session.commit()

        logger.info(
            f"Successfully connected Google Calendar for {user.email} ({user_info.email})"
        )
        return RedirectResponse(url="/settings?calendar_connected=true", status_code=302)

    except Exception as e:
        logger.error(f"OAuth callback failed: {e}")
        return RedirectResponse(
            url=f"/settings?calendar_error=auth_failed", status_code=302
        )


@router.post("/disconnect")
async def disconnect_google_calendar(
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> CalendarStatusResponse:
    """Disconnect Google Calendar and revoke access."""
    user_repo = SQLAlchemyUserRepository(session)
    user = await user_repo.get(UserId.from_string(current_user_id))

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    if not user.has_google_calendar_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Calendar is not connected",
        )

    container = await get_container()

    # Try to revoke the token with Google
    if container.google_calendar_adapter and user.encrypted_google_refresh_token:
        try:
            encryption = get_api_key_encryption()
            refresh_token = encryption.decrypt(user.encrypted_google_refresh_token)
            await container.google_calendar_adapter.revoke_token(refresh_token)
            logger.info(f"Revoked Google token for {user.email}")
        except Exception as e:
            logger.warning(f"Failed to revoke Google token: {e}")
            # Continue anyway - we'll still disconnect locally

    # Clear the connection
    updated_user = user.disconnect_google_calendar()
    await user_repo.update(updated_user)
    await session.commit()

    logger.info(f"Disconnected Google Calendar for {user.email}")
    return CalendarStatusResponse(
        connected=False,
        email=None,
        selected_calendar_id=None,
        calendar_enabled=False,
        sync_confirmed_only=False,
    )


@router.patch("/settings")
async def update_calendar_settings(
    data: CalendarSettingsUpdate,
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> CalendarStatusResponse:
    """Update Google Calendar settings."""
    user_repo = SQLAlchemyUserRepository(session)
    user = await user_repo.get(UserId.from_string(current_user_id))

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    # Build updates
    preference_updates = {}
    if data.selected_calendar_id is not None:
        preference_updates["google_calendar_id"] = data.selected_calendar_id
    if data.sync_confirmed_only is not None:
        preference_updates["calendar_sync_confirmed_only"] = data.sync_confirmed_only
    if data.calendar_enabled is not None:
        preference_updates["google_calendar_enabled"] = data.calendar_enabled

    if preference_updates:
        updated_user = user.update_preferences(**preference_updates)
        await user_repo.update(updated_user)
        await session.commit()
        user = updated_user

    return CalendarStatusResponse(
        connected=user.has_google_calendar_connected(),
        email=user.google_calendar_email,
        selected_calendar_id=user.preferences.google_calendar_id,
        calendar_enabled=user.preferences.google_calendar_enabled,
        sync_confirmed_only=user.preferences.calendar_sync_confirmed_only,
    )


@router.get("/calendars", response_model=list[GoogleCalendarInfo])
async def list_calendars(
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> list[GoogleCalendarInfo]:
    """List available Google Calendars for the connected account."""
    user_repo = SQLAlchemyUserRepository(session)
    user = await user_repo.get(UserId.from_string(current_user_id))

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    if not user.has_google_calendar_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Calendar is not connected",
        )

    container = await get_container()
    if not container.google_calendar_adapter:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar integration is not configured",
        )

    try:
        # Decrypt refresh token and get access token
        encryption = get_api_key_encryption()
        refresh_token = encryption.decrypt(user.encrypted_google_refresh_token)

        tokens = await container.google_calendar_adapter.refresh_access_token(
            refresh_token
        )

        # List calendars
        calendars = await container.google_calendar_adapter.list_calendars(
            tokens.access_token
        )

        return [
            GoogleCalendarInfo(
                id=cal.id,
                name=cal.name,
                is_primary=cal.is_primary,
                access_role=cal.access_role,
            )
            for cal in calendars
        ]

    except Exception as e:
        logger.error(f"Failed to list calendars: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch calendars from Google",
        )


class SyncEventRequest(BaseModel):
    """Request to sync an event to Google Calendar."""

    event_id: str


class SyncEventResponse(BaseModel):
    """Response after syncing an event."""

    success: bool
    google_event_id: str | None = None
    sync_status: str
    message: str


class GoogleEventInfo(BaseModel):
    """Information about an event from Google Calendar."""

    google_event_id: str
    google_calendar_id: str
    title: str
    description: str | None = None
    start_datetime: str | None = None
    end_datetime: str | None = None
    location: str | None = None
    is_all_day: bool = False


@router.post("/sync-event", response_model=SyncEventResponse)
async def sync_event_to_google(
    data: SyncEventRequest,
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> SyncEventResponse:
    """Sync a specific event to Google Calendar."""
    from agent_system.adapters.outbound.persistence import (
        SQLAlchemyExtractedEventRepository,
    )
    from agent_system.application.services import CalendarSyncService
    from agent_system.domain.value_objects import EventId

    container = await get_container()
    if not container.google_calendar_adapter:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar integration is not configured",
        )

    # Get user
    user_repo = SQLAlchemyUserRepository(session)
    user = await user_repo.get(UserId.from_string(current_user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    if not user.has_google_calendar_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Calendar is not connected",
        )

    # Get event
    event_repo = SQLAlchemyExtractedEventRepository(session)
    event = await event_repo.get(EventId.from_string(data.event_id))
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Event not found"
        )

    # Sync event
    sync_service = CalendarSyncService(container.google_calendar_adapter)
    updated_event = await sync_service.sync_event_to_google(event, user)

    # Save updated event
    await event_repo.update(updated_event)
    await session.commit()

    return SyncEventResponse(
        success=updated_event.google_sync_status.value == "synced",
        google_event_id=updated_event.google_event_id,
        sync_status=updated_event.google_sync_status.value,
        message="Event synced successfully" if updated_event.google_event_id else "Sync failed or not enabled",
    )


@router.get("/events", response_model=list[GoogleEventInfo])
async def get_google_events(
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> list[GoogleEventInfo]:
    """Get events from user's Google Calendar."""
    from agent_system.application.services import CalendarSyncService

    container = await get_container()
    if not container.google_calendar_adapter:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar integration is not configured",
        )

    user_repo = SQLAlchemyUserRepository(session)
    user = await user_repo.get(UserId.from_string(current_user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    if not user.has_google_calendar_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Calendar is not connected",
        )

    sync_service = CalendarSyncService(container.google_calendar_adapter)
    events = await sync_service.pull_events_from_google(user)

    return [
        GoogleEventInfo(
            google_event_id=e["google_event_id"],
            google_calendar_id=e["google_calendar_id"],
            title=e["title"],
            description=e.get("description"),
            start_datetime=e["start_datetime"].isoformat() if e.get("start_datetime") else None,
            end_datetime=e["end_datetime"].isoformat() if e.get("end_datetime") else None,
            location=e.get("location"),
            is_all_day=e.get("is_all_day", False),
        )
        for e in events
    ]


@router.delete("/sync-event/{event_id}")
async def delete_synced_event(
    event_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> SyncEventResponse:
    """Delete an event from Google Calendar (keeps local event)."""
    from agent_system.adapters.outbound.persistence import (
        SQLAlchemyExtractedEventRepository,
    )
    from agent_system.application.services import CalendarSyncService
    from agent_system.domain.value_objects import EventId

    container = await get_container()
    if not container.google_calendar_adapter:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar integration is not configured",
        )

    user_repo = SQLAlchemyUserRepository(session)
    user = await user_repo.get(UserId.from_string(current_user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    event_repo = SQLAlchemyExtractedEventRepository(session)
    event = await event_repo.get(EventId.from_string(event_id))
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Event not found"
        )

    if not event.google_event_id:
        return SyncEventResponse(
            success=True,
            google_event_id=None,
            sync_status="pending",
            message="Event was not synced to Google Calendar",
        )

    sync_service = CalendarSyncService(container.google_calendar_adapter)
    deleted = await sync_service.delete_event_from_google(event, user)

    if deleted:
        # Clear sync info from local event
        updated_event = event.clear_google_sync()
        await event_repo.update(updated_event)
        await session.commit()

    return SyncEventResponse(
        success=deleted,
        google_event_id=None if deleted else event.google_event_id,
        sync_status="pending" if deleted else "synced",
        message="Event removed from Google Calendar" if deleted else "Failed to delete from Google Calendar",
    )
