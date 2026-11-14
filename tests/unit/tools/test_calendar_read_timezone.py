"""Reading Google Calendar events back at the hour they were written for.

The bug this pins: Google returns times in the calendar's own zone
("2026-11-14T18:00:00-06:00"). The adapter dropped the offset without applying it,
so a 6 PM Central event was stored as "18:00 UTC" and shown at noon. No network.
"""

from datetime import datetime
from types import SimpleNamespace

import pytest

from agent_system.adapters.outbound.calendar.google_adapter import GoogleCalendarAdapter
from agent_system.adapters.outbound.llm import tools as tools_mod
from agent_system.adapters.outbound.persistence.models import UserModel

pytestmark = pytest.mark.unit

USER_ID = "11111111-1111-1111-1111-111111111111"

# What Google sends for events on a Central-time calendar on Saturday 14 November 2026.
HANGOUT = {"id": "g1", "summary": "Hangout with Ben Luis",
           "start": {"dateTime": "2026-11-14T18:00:00-06:00", "timeZone": "America/Chicago"},
           "end": {"dateTime": "2026-11-14T20:00:00-06:00", "timeZone": "America/Chicago"}}
BRUNCH_UTC = {"id": "g2", "summary": "Brunch", "start": {"dateTime": "2026-11-14T17:00:00Z"},
              "end": {"dateTime": "2026-11-14T18:00:00Z"}}
BIRTHDAY = {"id": "g3", "summary": "Dana's birthday", "start": {"date": "2026-11-14"}, "end": {"date": "2026-11-15"}}


def _parse(item):
    return GoogleCalendarAdapter.__new__(GoogleCalendarAdapter)._parse_google_event(item, "primary")


def test_a_time_with_an_offset_is_converted_to_utc_not_just_stripped():
    event = _parse(HANGOUT)
    # 6 PM Central is midnight UTC on the next day.
    assert event.start_datetime == datetime(2026, 11, 15, 0, 0)
    assert event.end_datetime == datetime(2026, 11, 15, 2, 0)
    assert event.start_datetime.tzinfo is None and not event.is_all_day


def test_a_time_already_in_utc_is_unchanged_and_an_all_day_event_keeps_its_date():
    assert _parse(BRUNCH_UTC).start_datetime == datetime(2026, 11, 14, 17, 0)
    birthday = _parse(BIRTHDAY)
    assert birthday.is_all_day and birthday.start_datetime == datetime(2026, 11, 14)


class _FakeSync:
    """Stands in for Google: returns the parsed events that start inside the requested window."""

    windows: list[tuple[datetime, datetime]] = []
    items = [HANGOUT, BRUNCH_UTC, BIRTHDAY]

    def __init__(self, adapter):
        pass

    async def pull_events_from_google(self, user, time_min=None, time_max=None, max_results=50):
        _FakeSync.windows.append((time_min, time_max))
        events = [_parse(item) for item in self.items]
        return [
            {"title": e.title, "description": e.description, "location": e.location,
             "start_datetime": e.start_datetime, "end_datetime": e.end_datetime, "is_all_day": e.is_all_day}
            for e in events
            # an all-day event's date is compared in local time by Google; the timed ones as instants
            if (e.is_all_day and e.start_datetime.date() == self.local_day) or
               (not e.is_all_day and time_min <= e.start_datetime <= time_max)
        ]


@pytest.fixture
async def session(async_session, monkeypatch):
    """A Central-time user with a connected calendar and no groups."""
    async_session.add(UserModel(id=USER_ID, email="u@example.com", hashed_password="x", timezone="America/Chicago"))
    await async_session.commit()
    user = SimpleNamespace(id=USER_ID, timezone="America/Chicago", has_google_calendar_connected=lambda: True,
                           preferences=SimpleNamespace(google_calendar_enabled=True, google_calendar_id=None))

    class Repo:
        def __init__(self, _session):
            pass

        async def get(self, _id):
            return user

    async def fake_container():
        return SimpleNamespace(google_calendar_adapter=object())

    _FakeSync.windows = []
    monkeypatch.setattr("agent_system.composition_root.container.get_container", fake_container)
    monkeypatch.setattr("agent_system.adapters.outbound.persistence.SQLAlchemyUserRepository", Repo)
    monkeypatch.setattr("agent_system.application.services.CalendarSyncService", _FakeSync)
    return async_session


async def _events_on(session, day: str):
    _FakeSync.local_day = datetime.fromisoformat(day).date()
    result = await tools_mod.get_upcoming_events(user_id=USER_ID, specific_date=day, temporal_filter="all",
                                                 session=session)
    assert result.success, result.message
    return result


async def test_a_central_evening_event_reads_back_at_the_same_hour(session):
    result = await _events_on(session, "2026-11-14")

    by_title = {e["title"]: e["datetime"] for e in result.data}
    assert by_title["Hangout with Ben Luis"] == "Saturday, November 14 at 06:00 PM CST"
    assert by_title["Brunch"] == "Saturday, November 14 at 11:00 AM CST"
    assert "12:00 PM" not in result.message  # the six-hours-early reading


async def test_an_event_at_midnight_utc_belongs_to_the_local_day_it_happens_on(session):
    # 6 PM Central on the 14th is 00:00 UTC on the 15th. It must be found when asking
    # about the 14th and must not appear on the 15th.
    saturday = await _events_on(session, "2026-11-14")
    sunday = await _events_on(session, "2026-11-15")

    assert _FakeSync.windows[0] == (datetime(2026, 11, 14, 6, 0), datetime(2026, 11, 15, 5, 59, 59))
    assert "Hangout with Ben Luis" in [e["title"] for e in saturday.data]
    assert "Hangout with Ben Luis" not in [e["title"] for e in sunday.data]


async def test_an_all_day_event_stays_on_its_own_date(session):
    result = await _events_on(session, "2026-11-14")
    when = {e["title"]: e["datetime"] for e in result.data}["Dana's birthday"]
    assert when == "Saturday, November 14 (all day)"  # not "Friday ... at 06:00 PM"


async def test_someone_in_no_groups_still_sees_their_google_calendar(session):
    result = await _events_on(session, "2026-11-14")
    assert len(result.data) == 3 and "not a member of any groups" not in result.message
