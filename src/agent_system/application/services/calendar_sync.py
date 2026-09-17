"""Calendar sync service for synchronizing events with Google Calendar."""

import logging
from datetime import datetime, timedelta

from agent_system.domain.entities import (
    CalendarEvent,
    CalendarEventSource,
    ExtractedEvent,
    GoogleCalendarSyncStatus,
    User,
)
from agent_system.domain.ports import GoogleCalendarPort
from agent_system.domain.value_objects import EventId
from agent_system.domain.utils.encryption import get_api_key_encryption

logger = logging.getLogger(__name__)


class CalendarSyncService:
    """Service for syncing events between the app and Google Calendar."""

    def __init__(self, google_calendar_adapter: GoogleCalendarPort):
        """Initialize the calendar sync service.

        Args:
            google_calendar_adapter: The Google Calendar port implementation
        """
        self.google_calendar = google_calendar_adapter
        self.encryption = get_api_key_encryption()

    async def _get_access_token(self, user: User) -> str | None:
        """Get a valid access token for the user.

        Args:
            user: The user to get the token for

        Returns:
            Access token or None if user doesn't have calendar connected
        """
        if not user.has_google_calendar_connected():
            return None

        if not user.encrypted_google_refresh_token:
            return None

        try:
            refresh_token = self.encryption.decrypt(user.encrypted_google_refresh_token)
            tokens = await self.google_calendar.refresh_access_token(refresh_token)
            return tokens.access_token
        except Exception as e:
            logger.error(f"Failed to refresh access token for {user.email}: {e}")
            return None

    async def sync_event_to_google(
        self,
        event: ExtractedEvent,
        user: User,
    ) -> ExtractedEvent:
        """Sync an extracted event to the user's Google Calendar.

        Args:
            event: The event to sync
            user: The user whose calendar to sync to

        Returns:
            Updated event with sync status
        """
        # Check if user has calendar sync enabled
        if not user.preferences.google_calendar_enabled:
            logger.debug(f"Calendar sync not enabled for user {user.email}")
            return event.model_copy(
                update={"google_sync_status": GoogleCalendarSyncStatus.NOT_ENABLED}
            )

        # Check if event has a datetime (can't sync events without dates)
        if not event.event_datetime:
            logger.debug(f"Event {event.id} has no datetime, skipping sync")
            return event

        # Get access token
        access_token = await self._get_access_token(user)
        if not access_token:
            logger.warning(f"No access token available for {user.email}")
            return event.mark_sync_failed()

        try:
            # Determine which calendar to use
            calendar_id = user.preferences.google_calendar_id or "primary"

            # Build event data
            # Use 1 hour duration by default
            end_time = event.event_datetime + timedelta(hours=1)

            # Build a CalendarEvent object using factory method
            calendar_event = CalendarEvent.create_from_extracted(
                user_id=user.id,
                extracted_event_id=event.id,
                title=event.title,
                description=event.description or f"Event from Agent System ({event.event_type.value})",
                start_datetime=event.event_datetime,
                end_datetime=end_time,
                location=event.location,
            )

            # Check if this is an update or create
            if event.google_event_id:
                # Update existing event
                etag = await self.google_calendar.update_event(
                    access_token=access_token,
                    calendar_id=calendar_id,
                    google_event_id=event.google_event_id,
                    event=calendar_event,
                )
                logger.info(f"Updated Google Calendar event {event.google_event_id} for event {event.id}")
                google_event_id = event.google_event_id
            else:
                # Create new event
                google_event_id, etag = await self.google_calendar.create_event(
                    access_token=access_token,
                    calendar_id=calendar_id,
                    event=calendar_event,
                )
                logger.info(f"Created Google Calendar event {google_event_id} for event {event.id}")

            return event.mark_synced_to_google(
                google_event_id=google_event_id,
                google_calendar_id=calendar_id,
            )

        except Exception as e:
            logger.error(f"Failed to sync event {event.id} to Google Calendar: {e}")
            return event.mark_sync_failed()

    async def create_event_for_user(
        self,
        user: User,
        title: str,
        start_utc: datetime,
        end_utc: datetime | None = None,
        description: str | None = None,
        location: str | None = None,
    ) -> tuple[str, str] | None:
        """Create a one-off event on the user's Google Calendar (an explicit
        "put this on my calendar" request, so the sync opt-in is not required,
        only a connected calendar).

        Returns (google_event_id, calendar_id) or None when not connected.
        """
        access_token = await self._get_access_token(user)
        if not access_token:
            return None
        calendar_id = user.preferences.google_calendar_id or "primary"
        calendar_event = CalendarEvent(
            id=EventId.generate(),
            user_id=user.id,
            title=title,
            description=description,
            start_datetime=start_utc,
            end_datetime=end_utc or start_utc + timedelta(hours=2),
            location=location,
            source=CalendarEventSource.MANUAL,
        )
        google_event_id, _etag = await self.google_calendar.create_event(
            access_token=access_token, calendar_id=calendar_id, event=calendar_event,
        )
        logger.info(f"Created ad-hoc Google Calendar event {google_event_id} for {user.email}")
        return google_event_id, calendar_id

    async def delete_event_from_google(
        self,
        event: ExtractedEvent,
        user: User,
    ) -> bool:
        """Delete an event from Google Calendar.

        Args:
            event: The event to delete
            user: The user whose calendar to delete from

        Returns:
            True if deleted successfully, False otherwise
        """
        if not event.google_event_id:
            return True  # Nothing to delete

        access_token = await self._get_access_token(user)
        if not access_token:
            return False

        try:
            calendar_id = event.google_calendar_id or user.preferences.google_calendar_id or "primary"
            await self.google_calendar.delete_event(
                access_token=access_token,
                calendar_id=calendar_id,
                event_id=event.google_event_id,
            )
            logger.info(f"Deleted Google Calendar event {event.google_event_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete event from Google Calendar: {e}")
            return False

    async def pull_events_from_google(
        self,
        user: User,
        time_min: datetime | None = None,
        time_max: datetime | None = None,
        max_results: int = 50,
    ) -> list[dict]:
        """Pull events from user's Google Calendar.

        Args:
            user: The user whose calendar to pull from
            time_min: Start of time range (default: now)
            time_max: End of time range (default: 30 days from now)
            max_results: Maximum number of events to return

        Returns:
            List of calendar events as dicts
        """
        if not user.preferences.google_calendar_enabled:
            return []

        access_token = await self._get_access_token(user)
        if not access_token:
            return []

        try:
            calendar_id = user.preferences.google_calendar_id or "primary"
            
            # Default time range: now to 30 days
            if time_min is None:
                time_min = datetime.utcnow()
            if time_max is None:
                time_max = time_min + timedelta(days=30)

            events = await self.google_calendar.list_events(
                access_token=access_token,
                calendar_id=calendar_id,
                time_min=time_min,
                time_max=time_max,
                max_results=max_results,
            )

            return [
                {
                    "google_event_id": e.google_event_id,
                    "google_calendar_id": e.google_calendar_id,
                    "title": e.title,
                    "description": e.description,
                    "start_datetime": e.start_datetime,
                    "end_datetime": e.end_datetime,
                    "location": e.location,
                    "is_all_day": e.is_all_day,
                }
                for e in events
            ]
        except Exception as e:
            logger.error(f"Failed to pull events from Google Calendar: {e}")
            return []
