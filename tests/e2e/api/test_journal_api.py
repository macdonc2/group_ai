"""Journal API: the entry lifecycle, the calendar of days, and that one user's journal
is invisible to another.

Two users, Alice (who writes everything here) and Mallory (a valid account with no
relationship to Alice). The memory pipeline's model, graph and calendar calls are
replaced with recorders, so no model or network call happens; the routes, the
repository and the background task that ties them together are real.
"""

import sqlite3
import time
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from starlette.testclient import TestClient

from agent_system.adapters.inbound.api import create_app
from agent_system.adapters.inbound.api.routes import journal as journal_routes
from agent_system.adapters.outbound.llm import journal_memory
from agent_system.adapters.outbound.llm.chat_agent import ChatLoopOutcome
from agent_system.composition_root.config import Settings

pytestmark = pytest.mark.e2e

API = "/api/v1"
PASSWORD = "correct-horse-battery"
SECRET = "Told Sam about the diagnosis today. Dinner with Sam on Friday at 7pm."


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A running app with Alice and Mallory, and recorders in place of models, graph and calendar."""
    from agent_system.composition_root.config import get_settings

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    get_settings.cache_clear()
    db_path = tmp_path / "journal.db"
    settings = Settings(openai_api_key="sk-test", database_url=f"sqlite+aiosqlite:///{db_path}", debug=False)

    calls = SimpleNamespace(remembered=[], forgotten=[], added=[], turns=[])
    graph = object()

    async def fake_ports(api_key):
        return graph, None

    async def fake_remember(**kwargs):
        calls.remembered.append(kwargs)
        return "done"

    async def fake_forget(kg, user_id, entry_id):
        calls.forgotten.append((kg, user_id, entry_id))
        return 1

    async def fake_suggest(body, entry_date, *, model, api_key):
        return [{"id": "sug1", "title": "Dinner with Sam", "when": "Friday at 7:00 PM", "location": None,
                 "status": "pending"}]

    async def fake_add_event(**kwargs):
        calls.added.append(kwargs)
        return SimpleNamespace(success=True, message="Added to your Google Calendar")

    async def fake_turn(message, *, deps, api_key, history):
        found = await deps.reader(None, None, "Sam", 20)
        calls.turns.append({"user_id": deps.user_id, "day": deps.day, "day_entries": deps.day_entries,
                            "found": found, "history": len(history)})
        return ChatLoopOutcome(response=f"I found {len(found)} entries about Sam.", stopped="answered",
                               steps=[{"tool": "read_journal"}])

    monkeypatch.setattr(journal_routes, "_memory_ports", fake_ports)
    monkeypatch.setattr(journal_routes, "add_event", fake_add_event)
    monkeypatch.setattr(journal_routes, "run_turn", fake_turn)
    monkeypatch.setattr(journal_memory, "remember_entry", fake_remember)
    monkeypatch.setattr(journal_memory, "forget_entry", fake_forget)
    monkeypatch.setattr(journal_memory, "suggest_calendar_events", fake_suggest)

    with TestClient(create_app(settings)) as client:
        boot = client.post(f"{API}/auth/bootstrap", json={"email": "alice@example.com", "password": PASSWORD})
        assert boot.status_code == 200, boot.text
        alice = boot.json()["access_token"]
        made = client.post(f"{API}/auth/register", json={"email": "mallory@example.com", "password": PASSWORD},
                           headers=_bearer(alice))
        assert made.status_code == 201, made.text
        mallory = client.post(f"{API}/auth/login",
                              json={"email": "mallory@example.com", "password": PASSWORD}).json()["access_token"]
        # Alice has a calendar connected (suggestions are only offered then) and lives far from UTC.
        with sqlite3.connect(db_path) as raw:
            raw.execute("UPDATE users SET encrypted_google_refresh_token = 'x', timezone = 'Pacific/Kiritimati' "
                        "WHERE email = 'alice@example.com'")
        yield SimpleNamespace(client=client, alice=_bearer(alice), mallory=_bearer(mallory),
                              alice_id=boot.json()["user"]["id"], calls=calls, graph=graph)
    get_settings.cache_clear()


def _write(world, body: str = SECRET, **extra) -> dict:
    r = world.client.post(f"{API}/journal/entries", json={"body": body, **extra}, headers=world.alice)
    assert r.status_code == 201, r.text
    return r.json()


def _settled(world, day: str, headers=None) -> list[dict]:
    """The day's entries once the background memory task has finished."""
    for _ in range(100):
        entries = world.client.get(f"{API}/journal/entries", params={"date": day}, headers=headers or world.alice).json()
        if all(e["memory_status"] != "pending" for e in entries):
            return entries
        time.sleep(0.02)
    raise AssertionError("memory task did not finish")


# -- the entry lifecycle ---------------------------------------------------


def test_an_entry_is_filed_under_today_in_the_users_timezone(world):
    local_today = datetime.now(ZoneInfo("Pacific/Kiritimati")).date().isoformat()

    entry = _write(world)
    assert entry["date"] == local_today  # UTC+14: often not the server's date

    days = world.client.get(f"{API}/journal/days", headers=world.alice).json()
    assert days["today"] == local_today and days["days"] == {local_today: 1}


def test_writing_feeds_memory_and_offers_but_never_adds_calendar_events(world):
    entry = _write(world)
    [settled] = _settled(world, entry["date"])

    assert settled["memory_status"] == "done"
    [remembered] = world.calls.remembered
    assert remembered["user_id"] == world.alice_id and remembered["entry_id"] == entry["id"]
    assert remembered["body"] == SECRET and remembered["kg"] is world.graph
    assert [s["status"] for s in settled["suggestions"]] == ["pending"]
    assert world.calls.added == []  # found in the entry, not written to the calendar


def test_a_suggested_event_is_added_once_and_only_on_a_click(world):
    entry = _write(world)
    _settled(world, entry["date"])
    url = f"{API}/journal/entries/{entry['id']}/suggestions/sug1"

    first = world.client.post(f"{url}/accept", headers=world.alice)
    again = world.client.post(f"{url}/accept", headers=world.alice)

    assert first.status_code == 200 and first.json()["suggestions"][0]["status"] == "added"
    assert again.status_code == 200
    assert len(world.calls.added) == 1
    assert world.calls.added[0]["title"] == "Dinner with Sam" and world.calls.added[0]["user_id"] == world.alice_id


def test_a_dismissed_suggestion_goes_away(world):
    entry = _write(world)
    _settled(world, entry["date"])
    r = world.client.post(f"{API}/journal/entries/{entry['id']}/suggestions/sug1/dismiss", headers=world.alice)
    assert r.status_code == 200 and r.json()["suggestions"] == []
    assert world.calls.added == []


def test_editing_rebuilds_memory_from_the_new_text(world):
    entry = _write(world)
    _settled(world, entry["date"])

    r = world.client.put(f"{API}/journal/entries/{entry['id']}", json={"body": "Rewritten."}, headers=world.alice)
    assert r.status_code == 200 and r.json()["memory_status"] == "pending"
    [settled] = _settled(world, entry["date"])

    assert settled["body"] == "Rewritten."
    assert [c["body"] for c in world.calls.remembered] == [SECRET, "Rewritten."]


def test_deleting_removes_the_entry_and_its_derived_memory(world):
    entry = _write(world)
    _settled(world, entry["date"])

    assert world.client.delete(f"{API}/journal/entries/{entry['id']}", headers=world.alice).status_code == 204

    assert _settled(world, entry["date"]) == []
    for _ in range(100):
        if world.calls.forgotten:
            break
        time.sleep(0.02)
    assert world.calls.forgotten == [(world.graph, world.alice_id, entry["id"])]


def test_an_entry_can_be_back_filled_but_not_written_for_the_future(world):
    assert _write(world, date="2026-01-05")["date"] == "2026-01-05"
    for bad in ("2999-01-01", "1999-12-31", "2026-02-30", "yesterday", "2026-1-5"):
        r = world.client.post(f"{API}/journal/entries", json={"body": "x", "date": bad}, headers=world.alice)
        assert r.status_code == 422, bad


def test_blank_entries_are_refused(world):
    assert world.client.post(f"{API}/journal/entries", json={"body": "   "}, headers=world.alice).status_code == 422
    assert world.calls.remembered == []


# -- one user's journal is invisible to another ----------------------------


def test_another_user_sees_an_empty_journal(world):
    entry = _write(world)
    _settled(world, entry["date"])

    listed = world.client.get(f"{API}/journal/entries", params={"date": entry["date"]}, headers=world.mallory)
    days = world.client.get(f"{API}/journal/days", params={"month": entry["date"][:7]}, headers=world.mallory)

    assert listed.status_code == 200 and listed.json() == []
    assert days.status_code == 200 and days.json()["days"] == {}


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("put", "", {"body": "Hijacked"}),
        ("delete", "", None),
        ("post", "/remember", None),
        ("post", "/suggestions/sug1/accept", None),
        ("post", "/suggestions/sug1/dismiss", None),
    ],
)
def test_another_users_entry_looks_missing(world, method, suffix, body):
    entry = _write(world)
    _settled(world, entry["date"])
    before = len(world.calls.remembered)

    r = world.client.request(method, f"{API}/journal/entries/{entry['id']}{suffix}", json=body, headers=world.mallory)
    assert r.status_code == 404  # not 403: the id's existence is not confirmed either

    # ...and nothing happened to it, to its memory, or to anyone's calendar.
    [mine] = _settled(world, entry["date"])
    assert mine["body"] == SECRET and mine["suggestions"][0]["status"] == "pending"
    assert len(world.calls.remembered) == before
    assert world.calls.added == [] and world.calls.forgotten == []


def test_the_side_chat_reads_and_stores_only_the_callers_journal(world):
    entry = _write(world)
    _settled(world, entry["date"])
    day = entry["date"]

    mallory = world.client.post(f"{API}/journal/chat", json={"date": day, "message": "What about Sam?"},
                                headers=world.mallory)
    alice = world.client.post(f"{API}/journal/chat", json={"date": day, "message": "What about Sam?"},
                              headers=world.alice)

    assert mallory.status_code == 200 and "I found 0 entries" in mallory.text
    assert alice.status_code == 200 and "I found 1 entries" in alice.text
    theirs, mine = world.calls.turns
    assert theirs["found"] == [] and theirs["day_entries"] == []
    assert mine["found"][0]["body"] == SECRET and mine["day_entries"][0]["body"] == SECRET

    # Each user's side chat holds only their own two messages.
    for headers in (world.alice, world.mallory):
        messages = world.client.get(f"{API}/journal/chat", params={"date": day}, headers=headers).json()
        assert [m["role"] for m in messages] == ["user", "assistant"]
    assert "1 entries" in world.client.get(f"{API}/journal/chat", params={"date": day},
                                           headers=world.alice).json()[1]["content"]

    # Clearing one user's chat leaves the other's alone.
    assert world.client.delete(f"{API}/journal/chat", params={"date": day}, headers=world.mallory).status_code == 204
    assert len(world.client.get(f"{API}/journal/chat", params={"date": day}, headers=world.alice).json()) == 2


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/journal/days", None),
        ("get", "/journal/entries?date=2026-01-05", None),
        ("post", "/journal/entries", {"body": "x"}),
        ("put", "/journal/entries/abc", {"body": "x"}),
        ("delete", "/journal/entries/abc", None),
        ("post", "/journal/entries/abc/remember", None),
        ("post", "/journal/entries/abc/suggestions/s/accept", None),
        ("get", "/journal/chat?date=2026-01-05", None),
        ("delete", "/journal/chat?date=2026-01-05", None),
        ("post", "/journal/chat", {"date": "2026-01-05", "message": "hi"}),
    ],
)
def test_every_journal_route_needs_a_token(world, method, path, body):
    assert world.client.request(method, f"{API}{path}", json=body).status_code == 401
    assert world.client.request(method, f"{API}{path}", json=body,
                                headers=_bearer("not-a-token")).status_code == 401
