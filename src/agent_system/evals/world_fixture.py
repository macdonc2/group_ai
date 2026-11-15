"""A frozen outside world for eval cases: the Houston events listing and the user's Google Calendar.

Without this, a case about events or the calendar depends on what the events service holds
today and on a real connected calendar, so it cannot be repeated. A case sets
`events_fixture` and/or `calendar_fixture`; the tools then read that instead of the network.

Two choices worth knowing:

- Dates are relative. A fixture says `day: 0` (today in Houston) or `day: 1`, never a calendar
  date, so "what's on today" stays a meaningful question on any day the suite runs and no clock
  has to be pinned across the many places the app reads the time.
- The substitution happens at the edge, below the code under test. Events replace the HTTP
  fetch, so selection, de-duplication and formatting all run for real. Calendar entries are
  built in the shape Google sends them (a local time with a UTC offset) and go through the real
  parser, because the bug this guards against was in that parser.

The hooks are installed only in eval processes and fall through to the real thing when a case
sets no fixture.
"""

from __future__ import annotations

import contextvars
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

HOUSTON = ZoneInfo("America/Chicago")


class FixtureEvent(BaseModel):
    """One record as the events service would return it, dated relative to today in Houston."""

    title: str
    day: int = 0                      # 0 = today, 1 = tomorrow, -1 = yesterday
    time: str | None = None           # "19:30" Houston local; None = the source gave a date only
    venue: str | None = None
    source: str = "Ticketmaster"
    url: str | None = None
    description: str | None = None
    categories: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    research: dict[str, Any] | None = None


class FixtureCalendarEntry(BaseModel):
    """One Google Calendar event, dated relative to today in the user's timezone."""

    summary: str
    day: int = 0
    start: str | None = None          # "18:00" local; None = an all-day event
    end: str | None = None
    location: str | None = None
    description: str | None = None


_events: contextvars.ContextVar[list[FixtureEvent] | None] = contextvars.ContextVar("eval_events", default=None)
_calendar: contextvars.ContextVar[tuple[list[FixtureCalendarEntry], str] | None] = contextvars.ContextVar(
    "eval_calendar", default=None)
_installed = False


def set_world(events: list[FixtureEvent] | None, calendar: list[FixtureCalendarEntry] | None,
              timezone: str) -> tuple[contextvars.Token, contextvars.Token]:
    return _events.set(events), _calendar.set((calendar, timezone) if calendar is not None else None)


def reset_world(tokens: tuple[contextvars.Token, contextvars.Token]) -> None:
    _events.reset(tokens[0])
    _calendar.reset(tokens[1])


def _clock(text: str) -> time:
    hour, minute = text.split(":")
    return time(int(hour), int(minute))


def build_events(fixture: list[FixtureEvent], now: datetime | None = None) -> list[Any]:
    """Fixture records as `HoustonEvent`s. A record with no time starts at local midnight, which is
    how a date-only listing arrives from the service."""
    from agent_system.adapters.outbound.houston_events import HoustonEvent

    today = (now or datetime.now(HOUSTON)).astimezone(HOUSTON).date()
    out = []
    for i, e in enumerate(fixture):
        local = datetime.combine(today + timedelta(days=e.day), _clock(e.time) if e.time else time(0, 0), HOUSTON)
        out.append(HoustonEvent(
            id=i + 1, title=e.title, start_time=local.astimezone(ZoneInfo("UTC")), location=e.venue, source=e.source,
            url=e.url, description=e.description, categories=e.categories, details=e.details, research=e.research))
    return out


def google_items(fixture: list[FixtureCalendarEntry], timezone: str, now: datetime | None = None) -> list[dict[str, Any]]:
    """Fixture entries in the JSON shape the Google Calendar API returns for a calendar in `timezone`."""
    tz = ZoneInfo(timezone)
    today = (now or datetime.now(tz)).astimezone(tz).date()
    items = []
    for i, e in enumerate(fixture):
        day = today + timedelta(days=e.day)
        item: dict[str, Any] = {"id": f"fixture-{i}", "summary": e.summary}
        if e.location:
            item["location"] = e.location
        if e.description:
            item["description"] = e.description
        if e.start is None:
            item["start"], item["end"] = {"date": day.isoformat()}, {"date": (day + timedelta(days=1)).isoformat()}
        else:
            start = datetime.combine(day, _clock(e.start), tz)
            end = datetime.combine(day, _clock(e.end), tz) if e.end else start + timedelta(hours=1)
            # isoformat() of an aware datetime carries the offset, e.g. 2026-11-14T18:00:00-06:00
            item["start"] = {"dateTime": start.isoformat(), "timeZone": timezone}
            item["end"] = {"dateTime": end.isoformat(), "timeZone": timezone}
        items.append(item)
    return items


def calendar_events(fixture: list[FixtureCalendarEntry], timezone: str, time_min: datetime, time_max: datetime,
                    now: datetime | None = None) -> list[dict[str, Any]]:
    """What the calendar tool gets back for a window: fixture entries parsed by the real Google parser.

    `time_min`/`time_max` are naive UTC, as the tool passes them to Google. Timed events are kept
    when they start inside the window; an all-day event when its date falls on a local day the
    window touches.
    """
    from agent_system.adapters.outbound.calendar.google_adapter import GoogleCalendarAdapter

    tz, utc = ZoneInfo(timezone), ZoneInfo("UTC")
    local_days = {time_min.replace(tzinfo=utc).astimezone(tz).date() + timedelta(days=n)
                  for n in range((time_max - time_min).days + 2)}
    last_day = time_max.replace(tzinfo=utc).astimezone(tz).date()
    parser = GoogleCalendarAdapter.__new__(GoogleCalendarAdapter)
    out = []
    for item in google_items(fixture, timezone, now):
        event = parser._parse_google_event(item, "primary")
        if event.is_all_day:
            keep = event.start_datetime.date() in local_days and event.start_datetime.date() <= last_day
        else:
            keep = time_min <= event.start_datetime <= time_max
        if keep:
            out.append({"title": event.title, "description": event.description, "location": event.location,
                        "start_datetime": event.start_datetime, "end_datetime": event.end_datetime,
                        "is_all_day": event.is_all_day})
    return out


def install_world_fixture_hook() -> None:
    """Wrap the events fetch and the Google Calendar pull once. Both chat engines reach them through
    `houston_events.py` and `tools.py`, so one hook covers the FSM and the loop."""
    global _installed
    if _installed:
        return
    from agent_system.adapters.outbound import houston_events
    from agent_system.adapters.outbound.llm import tools

    real_fetch = houston_events.HoustonEventsAdapter.get_latest_events
    real_pull = tools.pull_google_events

    async def get_latest_events(self: Any, limit: int = 30) -> list[Any]:
        fixture = _events.get()
        if fixture is None:
            return await real_fetch(self, limit)
        return build_events(fixture)[:limit]

    async def pull_google_events(session: Any, user_id: str, time_min: datetime, time_max: datetime) -> list[dict[str, Any]]:
        fixture = _calendar.get()
        if fixture is None:
            return await real_pull(session, user_id, time_min, time_max)
        entries, timezone = fixture
        return calendar_events(entries, timezone, time_min, time_max)

    houston_events.HoustonEventsAdapter.get_latest_events = get_latest_events
    tools.pull_google_events = pull_google_events
    _installed = True
