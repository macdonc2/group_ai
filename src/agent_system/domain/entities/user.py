"""User entity - represents a system user with preferences and patterns."""

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator

from agent_system.domain.value_objects import UserId


class UserPreferences(BaseModel):
    """User preferences and settings."""

    default_model: str = "openai:gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 4096
    auto_plan: bool = True  # Automatically create plans for complex tasks
    verbose_responses: bool = False
    preferred_tools: Annotated[list[str], Field(default_factory=list)]
    custom_settings: Annotated[dict[str, Any], Field(default_factory=dict)]
    
    # Google Calendar integration
    google_calendar_enabled: bool = False  # Opt-in toggle for calendar sync
    google_calendar_id: str | None = None  # None = use "primary" (default calendar)
    calendar_sync_confirmed_only: bool = True  # Only sync confirmed events to Google


class LearnedPattern(BaseModel):
    """A pattern learned from user interactions."""

    pattern_type: str  # e.g., "coding_style", "communication_preference"
    description: str
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    examples: Annotated[list[str], Field(default_factory=list)]
    learned_at: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    last_applied: datetime | None = None


class User(BaseModel):
    """User entity with identity, preferences, and learned patterns."""

    id: UserId
    email: str  # Allow .local domains for system users
    hashed_password: str
    
    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        """Validate email format, allowing .local for system users."""
        if not v or "@" not in v:
            raise ValueError("Invalid email format")
        return v.lower().strip()
    is_active: Annotated[bool, Field(default=True)]
    is_superuser: Annotated[bool, Field(default=False)]
    is_verified: Annotated[bool, Field(default=False)]
    encrypted_openai_api_key: str | None = None  # Encrypted user-specific API key
    encrypted_google_refresh_token: str | None = None  # Encrypted Google OAuth refresh token
    google_calendar_email: str | None = None  # Connected Google account email for display
    timezone: str = "UTC"  # User's timezone (e.g., "America/Chicago", "Europe/London")
    preferences: Annotated[UserPreferences, Field(default_factory=UserPreferences)]
    learned_patterns: Annotated[list[LearnedPattern], Field(default_factory=list)]
    created_at: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    updated_at: Annotated[datetime, Field(default_factory=datetime.utcnow)]

    @classmethod
    def create(
        cls,
        email: str,
        hashed_password: str,
        is_superuser: bool = False,
    ) -> "User":
        """Create a new user."""
        return cls(
            id=UserId.generate(),
            email=email,
            hashed_password=hashed_password,
            is_superuser=is_superuser,
        )

    def update_preferences(self, **kwargs: Any) -> "User":
        """Update user preferences."""
        new_preferences = self.preferences.model_copy(update=kwargs)
        return self.model_copy(
            update={
                "preferences": new_preferences,
                "updated_at": datetime.utcnow(),
            }
        )

    def add_learned_pattern(self, pattern: LearnedPattern) -> "User":
        """Add a learned pattern."""
        patterns = [*self.learned_patterns, pattern]
        return self.model_copy(
            update={
                "learned_patterns": patterns,
                "updated_at": datetime.utcnow(),
            }
        )

    def get_pattern(self, pattern_type: str) -> LearnedPattern | None:
        """Get a learned pattern by type."""
        for pattern in self.learned_patterns:
            if pattern.pattern_type == pattern_type:
                return pattern
        return None

    def activate(self) -> "User":
        """Activate the user."""
        return self.model_copy(
            update={"is_active": True, "updated_at": datetime.utcnow()}
        )

    def deactivate(self) -> "User":
        """Deactivate the user."""
        return self.model_copy(
            update={"is_active": False, "updated_at": datetime.utcnow()}
        )

    def verify(self) -> "User":
        """Verify the user."""
        return self.model_copy(
            update={"is_verified": True, "updated_at": datetime.utcnow()}
        )

    def set_encrypted_api_key(self, encrypted_key: str | None) -> "User":
        """Set the encrypted OpenAI API key."""
        return self.model_copy(
            update={
                "encrypted_openai_api_key": encrypted_key,
                "updated_at": datetime.utcnow(),
            }
        )

    def has_api_key(self) -> bool:
        """Check if the user has an API key configured."""
        return self.encrypted_openai_api_key is not None

    def set_timezone(self, timezone: str) -> "User":
        """Set the user's timezone (e.g., 'America/Chicago', 'Europe/London')."""
        return self.model_copy(
            update={
                "timezone": timezone,
                "updated_at": datetime.utcnow(),
            }
        )

    def connect_google_calendar(
        self, encrypted_refresh_token: str, email: str
    ) -> "User":
        """Connect Google Calendar with OAuth credentials."""
        new_preferences = self.preferences.model_copy(
            update={"google_calendar_enabled": True}
        )
        return self.model_copy(
            update={
                "encrypted_google_refresh_token": encrypted_refresh_token,
                "google_calendar_email": email,
                "preferences": new_preferences,
                "updated_at": datetime.utcnow(),
            }
        )

    def disconnect_google_calendar(self) -> "User":
        """Disconnect Google Calendar and clear credentials."""
        new_preferences = self.preferences.model_copy(
            update={
                "google_calendar_enabled": False,
                "google_calendar_id": None,
            }
        )
        return self.model_copy(
            update={
                "encrypted_google_refresh_token": None,
                "google_calendar_email": None,
                "preferences": new_preferences,
                "updated_at": datetime.utcnow(),
            }
        )

    def has_google_calendar_connected(self) -> bool:
        """Check if Google Calendar is connected."""
        return self.encrypted_google_refresh_token is not None

    def set_google_calendar_id(self, calendar_id: str | None) -> "User":
        """Set which Google Calendar to sync to (None = primary)."""
        new_preferences = self.preferences.model_copy(
            update={"google_calendar_id": calendar_id}
        )
        return self.model_copy(
            update={
                "preferences": new_preferences,
                "updated_at": datetime.utcnow(),
            }
        )
