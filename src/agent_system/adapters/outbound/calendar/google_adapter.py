"""Google Calendar API adapter implementation."""

import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from agent_system.domain.entities import CalendarEvent, CalendarEventSource, CalendarSyncStatus
from agent_system.domain.ports import (
    GoogleCalendarInfo,
    GoogleCalendarPort,
    GoogleUserInfo,
    OAuthTokens,
)
from agent_system.domain.value_objects import EventId, UserId

logger = logging.getLogger(__name__)


class GoogleCalendarAdapter(GoogleCalendarPort):
    """Adapter for Google Calendar API using httpx for async HTTP calls."""

    GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
    GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
    GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
    GOOGLE_CALENDAR_API = "https://www.googleapis.com/calendar/v3"

    SCOPES = [
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/userinfo.email",
    ]

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ):
        """Initialize the Google Calendar adapter.

        Args:
            client_id: Google OAuth client ID
            client_secret: Google OAuth client secret
            redirect_uri: OAuth callback URL
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def get_authorization_url(self, state: str) -> str:
        """Get the OAuth2 authorization URL for user consent."""
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.SCOPES),
            "access_type": "offline",  # Get refresh token
            "prompt": "consent",  # Force consent to get refresh token
            "state": state,
        }
        return f"{self.GOOGLE_AUTH_URL}?{urlencode(params)}"

    async def exchange_code_for_tokens(self, code: str) -> OAuthTokens:
        """Exchange authorization code for access and refresh tokens."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.GOOGLE_TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": self.redirect_uri,
                },
            )
            response.raise_for_status()
            data = response.json()

            expires_in = data.get("expires_in", 3600)
            expires_at = datetime.now(timezone.utc).replace(
                tzinfo=None
            ) + __import__("datetime").timedelta(seconds=expires_in)

            return OAuthTokens(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                expires_at=expires_at,
                token_type=data.get("token_type", "Bearer"),
            )

    async def get_user_info(self, access_token: str) -> GoogleUserInfo:
        """Get the authenticated user's Google account info."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            data = response.json()

            return GoogleUserInfo(
                email=data["email"],
                name=data.get("name"),
                picture=data.get("picture"),
            )

    async def refresh_access_token(self, refresh_token: str) -> OAuthTokens:
        """Refresh an expired access token."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.GOOGLE_TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            response.raise_for_status()
            data = response.json()

            expires_in = data.get("expires_in", 3600)
            expires_at = datetime.now(timezone.utc).replace(
                tzinfo=None
            ) + __import__("datetime").timedelta(seconds=expires_in)

            # Note: Refresh token may or may not be rotated
            return OAuthTokens(
                access_token=data["access_token"],
                refresh_token=data.get("refresh_token", refresh_token),
                expires_at=expires_at,
                token_type=data.get("token_type", "Bearer"),
            )

    async def revoke_token(self, token: str) -> bool:
        """Revoke OAuth access (disconnect account)."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.GOOGLE_REVOKE_URL,
                params={"token": token},
            )
            return response.status_code == 200

    async def list_calendars(self, access_token: str) -> list[GoogleCalendarInfo]:
        """List all calendars the user has access to."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.GOOGLE_CALENDAR_API}/users/me/calendarList",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            data = response.json()

            calendars = []
            for item in data.get("items", []):
                calendars.append(
                    GoogleCalendarInfo(
                        id=item["id"],
                        name=item.get("summary", "Untitled"),
                        is_primary=item.get("primary", False),
                        access_role=item.get("accessRole", "reader"),
                        background_color=item.get("backgroundColor"),
                    )
                )
            return calendars

    async def list_events(
        self,
        access_token: str,
        calendar_id: str,
        time_min: datetime | None = None,
        time_max: datetime | None = None,
        max_results: int = 100,
    ) -> list[CalendarEvent]:
        """List events from a calendar."""
        params: dict[str, Any] = {
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
        }

        if time_min:
            params["timeMin"] = time_min.isoformat() + "Z"
        if time_max:
            params["timeMax"] = time_max.isoformat() + "Z"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.GOOGLE_CALENDAR_API}/calendars/{calendar_id}/events",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )
            response.raise_for_status()
            data = response.json()

            events = []
            for item in data.get("items", []):
                event = self._parse_google_event(item, calendar_id)
                if event:
                    events.append(event)
            return events

    async def create_event(
        self,
        access_token: str,
        calendar_id: str,
        event: CalendarEvent,
    ) -> tuple[str, str | None]:
        """Create an event in Google Calendar."""
        body = self._build_google_event_body(event)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.GOOGLE_CALENDAR_API}/calendars/{calendar_id}/events",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
            data = response.json()

            return data["id"], data.get("etag")

    async def update_event(
        self,
        access_token: str,
        calendar_id: str,
        google_event_id: str,
        event: CalendarEvent,
    ) -> str | None:
        """Update an existing event in Google Calendar."""
        body = self._build_google_event_body(event)

        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{self.GOOGLE_CALENDAR_API}/calendars/{calendar_id}/events/{google_event_id}",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )

            if response.status_code == 409:  # Conflict
                return None

            response.raise_for_status()
            data = response.json()
            return data.get("etag")

    async def delete_event(
        self,
        access_token: str,
        calendar_id: str,
        google_event_id: str,
    ) -> bool:
        """Delete an event from Google Calendar."""
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self.GOOGLE_CALENDAR_API}/calendars/{calendar_id}/events/{google_event_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            return response.status_code in (200, 204, 410)  # 410 = already deleted

    async def get_event(
        self,
        access_token: str,
        calendar_id: str,
        google_event_id: str,
    ) -> CalendarEvent | None:
        """Get a single event from Google Calendar."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.GOOGLE_CALENDAR_API}/calendars/{calendar_id}/events/{google_event_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code == 404:
                return None

            response.raise_for_status()
            data = response.json()
            return self._parse_google_event(data, calendar_id)

    def _parse_google_event(
        self, item: dict[str, Any], calendar_id: str
    ) -> CalendarEvent | None:
        """Parse a Google Calendar event into a CalendarEvent entity."""
        try:
            # Handle all-day events vs timed events
            start = item.get("start", {})
            end = item.get("end", {})

            is_all_day = "date" in start
            if is_all_day:
                start_dt = datetime.fromisoformat(start["date"])
                end_dt = datetime.fromisoformat(end["date"]) if end.get("date") else None
            else:
                start_str = start.get("dateTime", "")
                start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                start_dt = start_dt.replace(tzinfo=None)  # Store as naive UTC

                end_str = end.get("dateTime", "")
                if end_str:
                    end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                    end_dt = end_dt.replace(tzinfo=None)
                else:
                    end_dt = None

            return CalendarEvent(
                id=EventId.generate(),
                user_id=UserId.generate(),  # Will be set by caller
                google_event_id=item["id"],
                google_calendar_id=calendar_id,
                title=item.get("summary", "Untitled Event"),
                description=item.get("description"),
                start_datetime=start_dt,
                end_datetime=end_dt,
                location=item.get("location"),
                is_all_day=is_all_day,
                source=CalendarEventSource.GOOGLE,
                sync_status=CalendarSyncStatus.SYNCED,
                last_synced_at=datetime.utcnow(),
                google_etag=item.get("etag"),
            )
        except Exception as e:
            logger.warning(f"Failed to parse Google event {item.get('id')}: {e}")
            return None

    def _build_google_event_body(self, event: CalendarEvent) -> dict[str, Any]:
        """Build the Google Calendar API event body from a CalendarEvent."""
        body: dict[str, Any] = {
            "summary": event.title,
        }

        if event.description:
            body["description"] = event.description

        if event.location:
            body["location"] = event.location

        if event.status == "tentative":
            body["status"] = "tentative"

        if event.is_all_day:
            body["start"] = {"date": event.start_datetime.strftime("%Y-%m-%d")}
            if event.end_datetime:
                body["end"] = {"date": event.end_datetime.strftime("%Y-%m-%d")}
            else:
                body["end"] = body["start"]
        else:
            body["start"] = {"dateTime": event.start_datetime.isoformat() + "Z"}
            if event.end_datetime:
                body["end"] = {"dateTime": event.end_datetime.isoformat() + "Z"}
            else:
                # Default to 1 hour duration
                end_dt = event.start_datetime + __import__("datetime").timedelta(hours=1)
                body["end"] = {"dateTime": end_dt.isoformat() + "Z"}

        return body
