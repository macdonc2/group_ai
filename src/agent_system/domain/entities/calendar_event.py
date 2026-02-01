"""CalendarEvent domain entity for synced calendar events."""

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from agent_system.domain.value_objects import EventId, UserId


class CalendarEventSource(str, Enum):
    """Source of a calendar event."""

    GOOGLE = "google"  # Imported from Google Calendar
    EXTRACTED = "extracted"  # Extracted from conversation by AI
    MANUAL = "manual"  # Manually created by user


class CalendarSyncStatus(str, Enum):
    """Sync status of a calendar event."""

    SYNCED = "synced"  # Successfully synced with Google
    PENDING = "pending"  # Waiting to be synced
    CONFLICT = "conflict"  # Conflict detected between local and remote
    LOCAL_ONLY = "local_only"  # Not synced to Google (user choice or not connected)
    ERROR = "error"  # Sync failed


class CalendarEvent(BaseModel):
    """A calendar event - either imported from Google or extracted from conversation."""

    id: EventId
    user_id: UserId

    # Sync identifiers
    google_event_id: str | None = None  # Google Calendar event ID if synced
    google_calendar_id: str | None = None  # Which Google Calendar it's in
    extracted_event_id: EventId | None = None  # If originated from AI extraction

    # Event details
    title: Annotated[str, Field(min_length=1, max_length=500)]
    description: str | None = None
    start_datetime: datetime
    end_datetime: datetime | None = None
    location: str | None = None
    is_all_day: bool = False

    # Sync metadata
    source: CalendarEventSource
    sync_status: CalendarSyncStatus = CalendarSyncStatus.LOCAL_ONLY
    last_synced_at: datetime | None = None
    google_etag: str | None = None  # For conflict detection

    # Timestamps
    created_at: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    updated_at: Annotated[datetime, Field(default_factory=datetime.utcnow)]

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, CalendarEvent):
            return self.id == other.id
        return False

    @classmethod
    def create_from_google(
        cls,
        user_id: UserId,
        google_event_id: str,
        google_calendar_id: str,
        title: str,
        start_datetime: datetime,
        end_datetime: datetime | None = None,
        description: str | None = None,
        location: str | None = None,
        is_all_day: bool = False,
        etag: str | None = None,
    ) -> "CalendarEvent":
        """Create a calendar event imported from Google."""
        return cls(
            id=EventId.generate(),
            user_id=user_id,
            google_event_id=google_event_id,
            google_calendar_id=google_calendar_id,
            title=title,
            description=description,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            location=location,
            is_all_day=is_all_day,
            source=CalendarEventSource.GOOGLE,
            sync_status=CalendarSyncStatus.SYNCED,
            last_synced_at=datetime.utcnow(),
            google_etag=etag,
        )

    @classmethod
    def create_from_extracted(
        cls,
        user_id: UserId,
        extracted_event_id: EventId,
        title: str,
        start_datetime: datetime,
        end_datetime: datetime | None = None,
        description: str | None = None,
        location: str | None = None,
    ) -> "CalendarEvent":
        """Create a calendar event from an AI-extracted event."""
        return cls(
            id=EventId.generate(),
            user_id=user_id,
            extracted_event_id=extracted_event_id,
            title=title,
            description=description,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            location=location,
            source=CalendarEventSource.EXTRACTED,
            sync_status=CalendarSyncStatus.PENDING,
        )

    @classmethod
    def create_manual(
        cls,
        user_id: UserId,
        title: str,
        start_datetime: datetime,
        end_datetime: datetime | None = None,
        description: str | None = None,
        location: str | None = None,
        is_all_day: bool = False,
    ) -> "CalendarEvent":
        """Create a manually created calendar event."""
        return cls(
            id=EventId.generate(),
            user_id=user_id,
            title=title,
            description=description,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            location=location,
            is_all_day=is_all_day,
            source=CalendarEventSource.MANUAL,
            sync_status=CalendarSyncStatus.PENDING,
        )

    def mark_synced(
        self, google_event_id: str, google_calendar_id: str, etag: str | None = None
    ) -> "CalendarEvent":
        """Mark the event as successfully synced to Google."""
        return self.model_copy(
            update={
                "google_event_id": google_event_id,
                "google_calendar_id": google_calendar_id,
                "google_etag": etag,
                "sync_status": CalendarSyncStatus.SYNCED,
                "last_synced_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        )

    def mark_sync_error(self) -> "CalendarEvent":
        """Mark the event as having a sync error."""
        return self.model_copy(
            update={
                "sync_status": CalendarSyncStatus.ERROR,
                "updated_at": datetime.utcnow(),
            }
        )

    def mark_conflict(self) -> "CalendarEvent":
        """Mark the event as having a conflict."""
        return self.model_copy(
            update={
                "sync_status": CalendarSyncStatus.CONFLICT,
                "updated_at": datetime.utcnow(),
            }
        )

    def update_details(
        self,
        title: str | None = None,
        description: str | None = None,
        start_datetime: datetime | None = None,
        end_datetime: datetime | None = None,
        location: str | None = None,
    ) -> "CalendarEvent":
        """Update event details and mark as pending sync."""
        updates: dict = {"updated_at": datetime.utcnow()}
        if self.sync_status == CalendarSyncStatus.SYNCED:
            updates["sync_status"] = CalendarSyncStatus.PENDING

        if title is not None:
            updates["title"] = title
        if description is not None:
            updates["description"] = description
        if start_datetime is not None:
            updates["start_datetime"] = start_datetime
        if end_datetime is not None:
            updates["end_datetime"] = end_datetime
        if location is not None:
            updates["location"] = location

        return self.model_copy(update=updates)

    @property
    def is_upcoming(self) -> bool:
        """Check if the event is in the future."""
        return self.start_datetime > datetime.utcnow()

    @property
    def needs_sync(self) -> bool:
        """Check if the event needs to be synced to Google."""
        return self.sync_status in (
            CalendarSyncStatus.PENDING,
            CalendarSyncStatus.ERROR,
        )

    @property
    def duration_minutes(self) -> int | None:
        """Get the event duration in minutes."""
        if self.end_datetime is None:
            return None
        delta = self.end_datetime - self.start_datetime
        return int(delta.total_seconds() / 60)
