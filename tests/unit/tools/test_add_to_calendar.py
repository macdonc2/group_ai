"""add_to_calendar: Houston match, natural-language date, and the not-connected path. No network."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agent_system.adapters.outbound.houston_events import HoustonEvent, format_houston_events_for_display
from agent_system.adapters.outbound.llm import tools as tools_mod


class _FakeUserRepo:
    def __init__(self, user):
        self._user = user

    async def get(self, _id):
        return self._user


class _FakeHoustonAdapter:
    def __init__(self, hits):
        self._hits = hits
        self.queries = []

    async def search_events(self, query=None, category=None, limit=20):
        self.queries.append(query)
        return [h for h in self._hits if query and query.lower() in h.title.lower()]

    async def close(self):
        pass


class _FakeSync:
    created = []

    def __init__(self, adapter):
        pass

    async def create_event_for_user(self, user, title, start_utc, end_utc=None, description=None, location=None):
        _FakeSync.created.append((title, start_utc, end_utc, location, description))
        return ("gcal-123", "primary")


def _user(connected=True, tz="America/Chicago"):
    return SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111", email="u@example.com", timezone=tz,
        has_google_calendar_connected=lambda: connected,
        preferences=SimpleNamespace(google_calendar_id=None),
    )


@pytest.fixture
def wire(monkeypatch):
    _FakeSync.created = []
    hits = [HoustonEvent(title="Punk Rock Garage Sale - September ALL INDOORS Market!", location="Bad Astronaut Brewing Co.",
                         start_time=datetime(2026, 9, 20, 19, 0), end_time=datetime(2026, 9, 20, 23, 0),
                         url="https://example.com/prgs", description="Indoor market")]
    adapter = _FakeHoustonAdapter(hits)

    async def fake_container():
        return SimpleNamespace(google_calendar_adapter=object())

    async def fake_parse(text, user_timezone="UTC", reference_time=None, api_key=None):
        return datetime(2026, 9, 22, 20, 0, tzinfo=timezone.utc) if "tuesday" in text.lower() else None

    monkeypatch.setattr("agent_system.composition_root.container.get_container", fake_container)
    monkeypatch.setattr("agent_system.adapters.outbound.persistence.SQLAlchemyUserRepository", lambda session: _FakeUserRepo(session.user))
    monkeypatch.setattr("agent_system.adapters.outbound.houston_events.HoustonEventsAdapter", lambda: adapter)
    monkeypatch.setattr("agent_system.application.services.CalendarSyncService", _FakeSync)
    monkeypatch.setattr("agent_system.application.services.datetime_parser.parse_vague_datetime", fake_parse)
    return adapter


@pytest.mark.unit
async def test_matches_houston_event_by_name(wire):
    session = SimpleNamespace(user=_user())
    r = await tools_mod.add_to_calendar(title="punk rock garage sale", when="punk rock garage sale", session=session, user_id="11111111-1111-1111-1111-111111111111")
    assert r.success, r.message
    title, start, end, location, description = _FakeSync.created[0]
    assert title.startswith("Punk Rock Garage Sale")
    assert start == datetime(2026, 9, 20, 19, 0) and end == datetime(2026, 9, 20, 23, 0)  # naive UTC passthrough
    assert location == "Bad Astronaut Brewing Co." and "https://example.com/prgs" in description
    assert "Sunday, September 20 at 2:00 PM CDT" in r.message  # 19:00 UTC shown in Houston time
    assert r.data["matched_houston_event"] is True


@pytest.mark.unit
async def test_falls_back_to_parsed_datetime(wire):
    session = SimpleNamespace(user=_user())
    r = await tools_mod.add_to_calendar(title="Dentist Tuesday at 3pm", when="Dentist Tuesday at 3pm", session=session, user_id="11111111-1111-1111-1111-111111111111")
    assert r.success, r.message
    title, start, end, *_ = _FakeSync.created[0]
    assert title == "Dentist Tuesday at 3pm" and start == datetime(2026, 9, 22, 20, 0) and end is None
    assert r.data["matched_houston_event"] is False


@pytest.mark.unit
async def test_no_match_and_no_date_asks_for_one(wire):
    session = SimpleNamespace(user=_user())
    r = await tools_mod.add_to_calendar(title="Zane's thing", when="Zane's thing", session=session, user_id="11111111-1111-1111-1111-111111111111")
    assert not r.success and "day and time" in r.message and _FakeSync.created == []


@pytest.mark.unit
async def test_not_connected(wire):
    session = SimpleNamespace(user=_user(connected=False))
    r = await tools_mod.add_to_calendar(title="anything", session=session, user_id="11111111-1111-1111-1111-111111111111")
    assert not r.success and "isn't connected" in r.message


@pytest.mark.unit
async def test_requires_session():
    r = await tools_mod.add_to_calendar(title="x")
    assert not r.success


@pytest.mark.unit
def test_houston_listing_shows_local_time():
    ev = HoustonEvent(title="Astros vs Royals", location="Daikin Park", start_time=datetime(2026, 9, 17, 23, 15))
    text = format_houston_events_for_display([ev])
    assert "06:15 PM CDT" in text and "11:15 PM" not in text
