# Google Calendar Integration Plan

**Status:** Implemented (September 2026)  
**Created:** 2026-01-29  

> Kept as design history. Calendar sync and the `add_to_calendar` tool both shipped;
> see the **Calendar** section of the README and `src/agent_system/docs/events-and-calendar.md`
> for how the delivered version actually behaves, which differs from this plan in places.

## Overview

Bidirectional sync between the Agent System and Google Calendar:
- **App → Google:** Sync confirmed extracted events to user's calendar
- **Google → App:** Import existing/new calendar events so the agent is aware of user's schedule

## Cost: Free (for typical usage)

Google Calendar API is **free** with generous quotas:
- **1,000,000 queries/day** (per project)
- **500 queries/100 seconds/user**
- No per-call charges

You only pay if you exceed these limits (unlikely for personal/small-team usage). OAuth consent screen verification is also free for under 100 users; above that requires verification (free, just a review process).

---

## Google Cloud Setup Requirements

### 1. Create Project & Enable API

```
Google Cloud Console → New Project → "Agent System Calendar"
                    → APIs & Services → Enable "Google Calendar API"
```

### 2. Configure OAuth Consent Screen

```
APIs & Services → OAuth consent screen
├── User Type: External (for any Google user) or Internal (Workspace only)
├── App name: "Agent System"
├── Support email: your email
├── Scopes: 
│   ├── https://www.googleapis.com/auth/calendar.readonly  (read events)
│   └── https://www.googleapis.com/auth/calendar.events    (create/edit events)
└── Test users: Add your email during development
```

### 3. Create OAuth Credentials

```
APIs & Services → Credentials → Create Credentials → OAuth client ID
├── Application type: Web application
├── Authorized redirect URIs:
│   ├── http://localhost:8000/api/calendar/callback  (dev)
│   └── https://agent.macdonml.com/api/calendar/callback  (prod)
└── Download client_secret.json
```

### 4. Store Secrets

Add to your secrets/environment:

```env
GOOGLE_CLIENT_ID=xxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxxx
GOOGLE_REDIRECT_URI=https://agent.macdonml.com/api/calendar/callback
```

For Kubernetes, add to Helm secrets.

---

## Requirements

### Functional Requirements

1. **Opt-in Toggle:** Users can enable/disable calendar sync in settings
2. **OAuth Flow:** Secure Google account connection via OAuth2
3. **Default Calendar:** Use user's primary calendar by default
4. **Calendar Selection:** Allow user to choose a specific calendar (optional)
5. **Event Sync (App → Google):** Confirmed extracted events sync to Google Calendar
6. **Event Import (Google → App):** Existing calendar events are visible to the agent
7. **Ongoing Sync:** New events added directly in Google Calendar are imported
8. **Disconnect:** Users can revoke access and disconnect their account

### Non-Functional Requirements

1. **Security:** Refresh tokens must be encrypted at rest
2. **Privacy:** Only access calendar data, not other Google services
3. **Reliability:** Handle token expiration gracefully with auto-refresh
4. **Performance:** Polling interval of 15 minutes (configurable)

---

## Implementation Plan

### Phase 1: Foundation (Backend)

| Task | Description | Files |
|------|-------------|-------|
| 1.1 | Add `google_calendar_enabled` and `google_calendar_id` to `UserPreferences` | `domain/entities/user.py` |
| 1.2 | Add `encrypted_google_refresh_token` to `UserModel` | `adapters/outbound/persistence/models.py` |
| 1.3 | Create DB migration for new fields | `alembic/versions/xxx_add_calendar_fields.py` |
| 1.4 | Create `CalendarEvent` entity | `domain/entities/calendar_event.py` |
| 1.5 | Create `CalendarEventModel` SQLAlchemy model | `adapters/outbound/persistence/models.py` |
| 1.6 | Create `GoogleCalendarPort` interface | `domain/ports/calendar.py` |
| 1.7 | Create `GoogleCalendarAdapter` implementation | `adapters/outbound/calendar/google.py` |
| 1.8 | Add `google-api-python-client` dependency | `pyproject.toml` |

### Phase 2: OAuth Flow

| Task | Description | Files |
|------|-------------|-------|
| 2.1 | Create OAuth initiation endpoint | `POST /api/calendar/connect` |
| 2.2 | Create OAuth callback handler | `GET /api/calendar/callback` |
| 2.3 | Implement token encryption/storage | Reuse existing `Fernet` encryption pattern |
| 2.4 | Create disconnect endpoint | `POST /api/calendar/disconnect` |
| 2.5 | Create calendar list endpoint | `GET /api/calendar/calendars` |

### Phase 3: Sync Logic

| Task | Description | Files |
|------|-------------|-------|
| 3.1 | App → Google: Sync on event confirmation | Trigger in `ExtractedEvent.confirm()` |
| 3.2 | Google → App: Initial import on connect | In OAuth callback |
| 3.3 | Google → App: Periodic sync (polling) | Background task every 15 min |
| 3.4 | Implement conflict detection | Match by title + datetime |
| 3.5 | Handle event updates and deletions | Two-way sync |
| 3.6 | Store `google_event_id` on synced events | Link for updates |

### Phase 4: Frontend

| Task | Description | Files |
|------|-------------|-------|
| 4.1 | Add calendar toggle in Settings | `frontend/src/components/Settings.tsx` |
| 4.2 | Add "Connect Google Account" button | OAuth redirect |
| 4.3 | Show connection status | "Connected as user@gmail.com" |
| 4.4 | Add calendar selector dropdown | After successful connection |
| 4.5 | Add "Add to Calendar" button on event cards | Manual sync trigger |
| 4.6 | Show sync status indicators | Synced ✓, Pending, Conflict |

### Phase 5: Agent Awareness

| Task | Description | Files |
|------|-------------|-------|
| 5.1 | Create `get_calendar_events` tool | `adapters/outbound/llm/tools.py` |
| 5.2 | Include upcoming events in context | Modify prompt assembly |
| 5.3 | Enable conflict detection in responses | "That conflicts with your dentist appointment" |
| 5.4 | Add scheduling suggestions | "You're free at 2pm and 4pm tomorrow" |

---

## Data Model

### New Entity: CalendarEvent

```python
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from agent_system.domain.value_objects import EventId, UserId


class CalendarEvent(BaseModel):
    """A calendar event - either imported from Google or extracted from conversation."""
    
    id: EventId
    user_id: UserId
    
    # Sync identifiers
    google_event_id: str | None = None  # If synced from/to Google
    extracted_event_id: EventId | None = None  # If originated from extraction
    
    # Event details
    title: str
    description: str | None = None
    start_datetime: datetime
    end_datetime: datetime | None = None
    location: str | None = None
    is_all_day: bool = False
    
    # Sync metadata
    source: Literal["google", "extracted", "manual"]
    sync_status: Literal["synced", "pending", "conflict", "local_only"]
    last_synced_at: datetime | None = None
    google_calendar_id: str | None = None  # Which calendar it's in
    
    created_at: datetime
    updated_at: datetime
```

### Updated UserPreferences

```python
class UserPreferences(BaseModel):
    """User preferences and settings."""
    
    # Existing fields...
    default_model: str = "openai:gpt-5.2"
    temperature: float = 0.7
    max_tokens: int = 4096
    auto_plan: bool = True
    verbose_responses: bool = False
    preferred_tools: list[str] = []
    custom_settings: dict[str, Any] = {}
    
    # NEW: Google Calendar integration
    google_calendar_enabled: bool = False
    google_calendar_id: str | None = None  # None = use "primary" (default calendar)
    calendar_sync_confirmed_only: bool = True  # Only sync confirmed events
    calendar_sync_interval_minutes: int = 15  # Polling interval
```

### Updated UserModel (SQLAlchemy)

```python
class UserModel(Base):
    __tablename__ = "users"
    
    # Existing fields...
    
    # NEW: Encrypted Google OAuth refresh token
    encrypted_google_refresh_token: Mapped[str | None] = mapped_column(
        String(2048), nullable=True
    )
    google_calendar_email: Mapped[str | None] = mapped_column(
        String(320), nullable=True
    )  # For display: "Connected as user@gmail.com"
```

---

## API Endpoints

### Calendar Connection

```
POST /api/calendar/connect
→ Returns: { "auth_url": "https://accounts.google.com/o/oauth2/..." }

GET /api/calendar/callback?code=xxx&state=xxx
→ Handles OAuth callback, stores tokens, redirects to frontend

POST /api/calendar/disconnect
→ Revokes access, clears tokens

GET /api/calendar/status
→ Returns: { "connected": true, "email": "user@gmail.com", "calendar_id": "primary" }

GET /api/calendar/calendars
→ Returns: [{ "id": "primary", "name": "My Calendar" }, ...]

PATCH /api/calendar/settings
→ Body: { "calendar_id": "xxx", "sync_confirmed_only": true }
```

### Event Sync

```
GET /api/calendar/events?start=2026-01-01&end=2026-02-01
→ Returns: [CalendarEvent, ...]

POST /api/calendar/events/{event_id}/sync
→ Manually sync a specific extracted event to Google

POST /api/calendar/sync
→ Trigger full sync (import from Google)
```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Frontend (React)                             │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  Settings Page                                                  │ │
│  │  ┌────────────────────────────────────────────────────────────┐│ │
│  │  │ Google Calendar                                            ││ │
│  │  │ [✓] Sync events to Google Calendar                         ││ │
│  │  │                                                            ││ │
│  │  │ Connected as: macdonc2@gmail.com  [Disconnect]             ││ │
│  │  │                                                            ││ │
│  │  │ Calendar: [Primary Calendar     ▼]                         ││ │
│  │  │ [✓] Only sync confirmed events                             ││ │
│  │  └────────────────────────────────────────────────────────────┘│ │
│  └────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Backend (FastAPI)                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │
│  │ Calendar Routes │  │ Event Routes    │  │ Background Tasks    │  │
│  │ /api/calendar/* │  │ /api/events/*   │  │ sync_calendars()    │  │
│  └────────┬────────┘  └────────┬────────┘  └──────────┬──────────┘  │
│           │                    │                      │              │
│           └────────────────────┼──────────────────────┘              │
│                                ▼                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                   GoogleCalendarPort                          │  │
│  │  - get_auth_url() → str                                       │  │
│  │  - exchange_code(code) → tokens                               │  │
│  │  - list_calendars(user) → list[Calendar]                      │  │
│  │  - list_events(user, start, end) → list[Event]                │  │
│  │  - create_event(user, event) → google_event_id                │  │
│  │  - update_event(user, google_id, event)                       │  │
│  │  - delete_event(user, google_id)                              │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                │                                     │
│                                ▼                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                 GoogleCalendarAdapter                         │  │
│  │  - Uses google-api-python-client                              │  │
│  │  - Handles OAuth2 token refresh                               │  │
│  │  - Maps domain events ↔ Google Calendar events                │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                        ┌───────────────────┐
                        │  Google Calendar  │
                        │       API         │
                        └───────────────────┘
```

---

## Timeline Estimate

| Phase | Effort | Dependencies |
|-------|--------|--------------|
| Phase 1: Foundation | 2-3 hours | None |
| Phase 2: OAuth Flow | 2-3 hours | Phase 1, Google Cloud setup |
| Phase 3: Sync Logic | 3-4 hours | Phase 2 |
| Phase 4: Frontend | 2-3 hours | Phase 2 |
| Phase 5: Agent Awareness | 1-2 hours | Phase 3 |
| **Total** | **10-15 hours** | |

---

## Dependencies to Add

```toml
# pyproject.toml
[project.dependencies]
# ... existing deps ...
google-api-python-client = "^2.100.0"
google-auth-oauthlib = "^1.2.0"
google-auth-httplib2 = "^0.2.0"
```

---

## Security Considerations

1. **Token Storage:** Google refresh tokens must be encrypted using the same `Fernet` pattern as OpenAI API keys
2. **Scope Minimization:** Only request `calendar.events` scope (not full calendar access)
3. **Token Revocation:** Provide clear disconnect option that revokes Google access
4. **HTTPS Only:** OAuth redirect URIs must use HTTPS in production
5. **State Parameter:** Use CSRF protection in OAuth flow via `state` parameter

---

## Future Enhancements

1. **Webhook Support:** Replace polling with Google Calendar push notifications for real-time updates
2. **Multiple Calendars:** Allow syncing to multiple calendars (work, personal, etc.)
3. **Event Templates:** Create recurring events from conversation patterns
4. **Smart Scheduling:** Agent suggests optimal meeting times based on calendar availability
5. **Calendar Sharing:** In group chats, find common free times across members
