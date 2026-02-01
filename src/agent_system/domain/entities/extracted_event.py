"""ExtractedEvent domain entity for AI-detected events from conversations."""

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field

from agent_system.domain.value_objects import EventId, GroupId, MessageId, UserId


class EventType(str, Enum):
    """Type of extracted event."""

    MEETING = "meeting"
    DEADLINE = "deadline"
    ACTIVITY = "activity"
    OBLIGATION = "obligation"


class GoogleCalendarSyncStatus(str, Enum):
    """Status of Google Calendar sync for an event."""

    PENDING = "pending"  # Not yet synced
    SYNCED = "synced"  # Successfully synced
    FAILED = "failed"  # Sync failed
    NOT_ENABLED = "not_enabled"  # User doesn't have calendar sync enabled


class ExtractedEvent(BaseModel):
    """An event extracted from group conversation by AI."""

    id: EventId
    group_id: GroupId
    title: Annotated[str, Field(min_length=1, max_length=255)]
    description: str | None = None
    event_type: EventType
    event_datetime: datetime | None = None
    location: str | None = None
    participant_ids: Annotated[list[UserId], Field(default_factory=list)]
    source_message_id: MessageId | None = None
    confidence: Annotated[float, Field(ge=0.0, le=1.0, default=0.0)]
    is_confirmed: bool = False
    created_at: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    
    # Google Calendar sync fields
    google_event_id: str | None = None
    google_calendar_id: str | None = None
    google_sync_status: GoogleCalendarSyncStatus = GoogleCalendarSyncStatus.PENDING
    google_synced_at: datetime | None = None

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ExtractedEvent):
            return self.id == other.id
        return False

    @classmethod
    def create(
        cls,
        group_id: GroupId,
        title: str,
        event_type: EventType,
        description: str | None = None,
        event_datetime: datetime | None = None,
        location: str | None = None,
        participant_ids: list[UserId] | None = None,
        source_message_id: MessageId | None = None,
        confidence: float = 0.0,
    ) -> "ExtractedEvent":
        """Create a new extracted event."""
        return cls(
            id=EventId.generate(),
            group_id=group_id,
            title=title,
            description=description,
            event_type=event_type,
            event_datetime=event_datetime,
            location=location,
            participant_ids=participant_ids or [],
            source_message_id=source_message_id,
            confidence=confidence,
        )

    def confirm(self) -> "ExtractedEvent":
        """Mark the event as confirmed by a user."""
        return self.model_copy(update={"is_confirmed": True})

    def update(
        self,
        title: str | None = None,
        description: str | None = None,
        event_datetime: datetime | None = None,
        location: str | None = None,
    ) -> "ExtractedEvent":
        """Update event details."""
        updates = {}
        if title is not None:
            updates["title"] = title
        if description is not None:
            updates["description"] = description
        if event_datetime is not None:
            updates["event_datetime"] = event_datetime
        if location is not None:
            updates["location"] = location
        return self.model_copy(update=updates)

    def add_participant(self, user_id: UserId) -> "ExtractedEvent":
        """Add a participant to the event."""
        if user_id in self.participant_ids:
            return self
        return self.model_copy(
            update={"participant_ids": [*self.participant_ids, user_id]}
        )

    def remove_participant(self, user_id: UserId) -> "ExtractedEvent":
        """Remove a participant from the event."""
        return self.model_copy(
            update={"participant_ids": [p for p in self.participant_ids if p != user_id]}
        )

    @property
    def is_upcoming(self) -> bool:
        """Check if the event is in the future."""
        if self.event_datetime is None:
            return True  # Unknown datetime, assume upcoming
        return self.event_datetime > datetime.utcnow()

    @property
    def participant_count(self) -> int:
        """Get the number of participants."""
        return len(self.participant_ids)

    @property
    def is_synced_to_google(self) -> bool:
        """Check if this event is synced to Google Calendar."""
        return self.google_event_id is not None and self.google_sync_status == GoogleCalendarSyncStatus.SYNCED

    def mark_synced_to_google(
        self,
        google_event_id: str,
        google_calendar_id: str,
    ) -> "ExtractedEvent":
        """Mark the event as synced to Google Calendar."""
        return self.model_copy(
            update={
                "google_event_id": google_event_id,
                "google_calendar_id": google_calendar_id,
                "google_sync_status": GoogleCalendarSyncStatus.SYNCED,
                "google_synced_at": datetime.utcnow(),
            }
        )

    def mark_sync_failed(self) -> "ExtractedEvent":
        """Mark the event sync as failed."""
        return self.model_copy(
            update={"google_sync_status": GoogleCalendarSyncStatus.FAILED}
        )

    def clear_google_sync(self) -> "ExtractedEvent":
        """Clear Google Calendar sync info (for re-sync or after deletion)."""
        return self.model_copy(
            update={
                "google_event_id": None,
                "google_calendar_id": None,
                "google_sync_status": GoogleCalendarSyncStatus.PENDING,
                "google_synced_at": None,
            }
        )
