"""Port for Google Calendar integration."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from agent_system.domain.entities import CalendarEvent
from agent_system.domain.value_objects import UserId


@dataclass
class GoogleCalendarInfo:
    """Information about a Google Calendar."""

    id: str
    name: str
    is_primary: bool
    access_role: str  # "owner", "writer", "reader"
    background_color: str | None = None


@dataclass
class OAuthTokens:
    """OAuth2 tokens from Google."""

    access_token: str
    refresh_token: str
    expires_at: datetime
    token_type: str = "Bearer"


@dataclass
class GoogleUserInfo:
    """User information from Google."""

    email: str
    name: str | None = None
    picture: str | None = None


class GoogleCalendarPort(ABC):
    """Port for Google Calendar operations.

    This port defines the interface for interacting with Google Calendar API.
    The adapter implementation handles OAuth, token refresh, and API calls.
    """

    @abstractmethod
    def get_authorization_url(self, state: str) -> str:
        """Get the OAuth2 authorization URL for user consent.

        Args:
            state: Random state parameter for CSRF protection

        Returns:
            URL to redirect user to for Google OAuth consent
        """
        ...

    @abstractmethod
    async def exchange_code_for_tokens(self, code: str) -> OAuthTokens:
        """Exchange authorization code for access and refresh tokens.

        Args:
            code: Authorization code from OAuth callback

        Returns:
            OAuth tokens including refresh token for storage
        """
        ...

    @abstractmethod
    async def get_user_info(self, access_token: str) -> GoogleUserInfo:
        """Get the authenticated user's Google account info.

        Args:
            access_token: Valid OAuth access token

        Returns:
            User's email and profile info
        """
        ...

    @abstractmethod
    async def refresh_access_token(self, refresh_token: str) -> OAuthTokens:
        """Refresh an expired access token.

        Args:
            refresh_token: Stored refresh token

        Returns:
            New OAuth tokens (refresh token may be rotated)
        """
        ...

    @abstractmethod
    async def revoke_token(self, token: str) -> bool:
        """Revoke OAuth access (disconnect account).

        Args:
            token: Access or refresh token to revoke

        Returns:
            True if revocation succeeded
        """
        ...

    @abstractmethod
    async def list_calendars(self, access_token: str) -> list[GoogleCalendarInfo]:
        """List all calendars the user has access to.

        Args:
            access_token: Valid OAuth access token

        Returns:
            List of calendar info objects
        """
        ...

    @abstractmethod
    async def list_events(
        self,
        access_token: str,
        calendar_id: str,
        time_min: datetime | None = None,
        time_max: datetime | None = None,
        max_results: int = 100,
    ) -> list[CalendarEvent]:
        """List events from a calendar.

        Args:
            access_token: Valid OAuth access token
            calendar_id: Calendar ID ("primary" for default)
            time_min: Only return events after this time
            time_max: Only return events before this time
            max_results: Maximum number of events to return

        Returns:
            List of calendar events
        """
        ...

    @abstractmethod
    async def create_event(
        self,
        access_token: str,
        calendar_id: str,
        event: CalendarEvent,
    ) -> tuple[str, str | None]:
        """Create an event in Google Calendar.

        Args:
            access_token: Valid OAuth access token
            calendar_id: Calendar ID ("primary" for default)
            event: Calendar event to create

        Returns:
            Tuple of (google_event_id, etag)
        """
        ...

    @abstractmethod
    async def update_event(
        self,
        access_token: str,
        calendar_id: str,
        google_event_id: str,
        event: CalendarEvent,
    ) -> str | None:
        """Update an existing event in Google Calendar.

        Args:
            access_token: Valid OAuth access token
            calendar_id: Calendar ID
            google_event_id: Google's event ID
            event: Updated event data

        Returns:
            New etag if successful, None if conflict
        """
        ...

    @abstractmethod
    async def delete_event(
        self,
        access_token: str,
        calendar_id: str,
        google_event_id: str,
    ) -> bool:
        """Delete an event from Google Calendar.

        Args:
            access_token: Valid OAuth access token
            calendar_id: Calendar ID
            google_event_id: Google's event ID

        Returns:
            True if deletion succeeded
        """
        ...

    @abstractmethod
    async def get_event(
        self,
        access_token: str,
        calendar_id: str,
        google_event_id: str,
    ) -> CalendarEvent | None:
        """Get a single event from Google Calendar.

        Args:
            access_token: Valid OAuth access token
            calendar_id: Calendar ID
            google_event_id: Google's event ID

        Returns:
            Calendar event or None if not found
        """
        ...
