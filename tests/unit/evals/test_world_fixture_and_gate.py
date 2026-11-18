"""Frozen events and calendar data for eval cases, and the hard gate on the incidents suite."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agent_system.adapters.outbound.houston_events import format_houston_events_for_display, select_events
from agent_system.evals import world_fixture as world
from agent_system.evals.runner import summarize
from agent_system.evals.schema import EvalCase, load_suite
from agent_system.evals.scorers import score_mentions

pytestmark = pytest.mark.unit

CT = ZoneInfo("America/Chicago")
NOW = datetime(2026, 11, 14, 10, 0, tzinfo=CT)       # Saturday morning in Houston, standard time
SUMMER = datetime(2026, 7, 4, 10, 0, tzinfo=CT)      # daylight time: the offset is -05:00


def test_fixture_events_are_dated_relative_to_today_in_houston():
    events = world.build_events([
        world.FixtureEvent(title="Late Show", time="23:30", venue="Scout Bar"),
        world.FixtureEvent(title="Date Only", day=1),
        world.FixtureEvent(title="Yesterday", day=-1, time="20:00"),
    ], NOW)
    assert events[0].start_time == datetime(2026, 11, 15, 5, 30, tzinfo=ZoneInfo("UTC"))   # 11:30 PM Central
    assert events[1].start_time.astimezone(CT) == datetime(2026, 11, 15, 0, 0, tzinfo=CT)  # midnight = no time given
    assert events[2].start_time.astimezone(CT).date().isoformat() == "2026-11-13"


def test_the_incident_fixture_goes_through_the_real_selection_and_merge():
    suite = load_suite("incidents")
    case = next(c for c in suite.cases if c.id == "one_festival_is_listed_once")
    shown, total = select_events(world.build_events(case.events_fixture, NOW), when="today", now=NOW)
    text = format_houston_events_for_display(shown, total)
    assert text.count("Breakaway") == 1 and "Breakaway Houston 2026" not in text    # four records, one line
    assert "12:00 PM" in text and "ticketmaster.com/event/breakaway" in text        # the ticketing source wins
    assert "Rodeo Kickoff" not in text and "Bayou Brunch Ride" not in text          # other days stay out
    assert total == 4


def test_calendar_fixture_is_what_google_sends_and_is_read_by_the_real_parser():
    entries = [world.FixtureCalendarEntry(summary="Hangout with Ben Luis", day=1, start="18:00", end="20:00"),
               world.FixtureCalendarEntry(summary="Dana's birthday", day=1)]
    hangout, birthday = world.google_items(entries, "America/Chicago", NOW)
    assert hangout["start"] == {"dateTime": "2026-11-15T18:00:00-06:00", "timeZone": "America/Chicago"}
    assert birthday["start"] == {"date": "2026-11-15"} and birthday["end"] == {"date": "2026-11-16"}
    assert world.google_items(entries, "America/Chicago", SUMMER)[0]["start"]["dateTime"].endswith("-05:00")

    # the tool asks for "tomorrow" as a naive-UTC window: local midnight to 23:59:59
    found = world.calendar_events(entries, "America/Chicago", datetime(2026, 11, 15, 6, 0), datetime(2026, 11, 16, 5, 59, 59), NOW)
    by_title = {e["title"]: e for e in found}
    assert by_title["Hangout with Ben Luis"]["start_datetime"] == datetime(2026, 11, 16, 0, 0)   # 6 PM Central in UTC
    assert by_title["Dana's birthday"]["is_all_day"]
    # and nothing leaks into today's window
    assert world.calendar_events(entries, "America/Chicago", datetime(2026, 11, 14, 6, 0), datetime(2026, 11, 15, 5, 59, 59), NOW) == []


def test_putting_the_old_calendar_bug_back_changes_what_the_fixture_returns(monkeypatch):
    # The fixture is only a regression test if it exercises the parser that had the bug.
    from agent_system.adapters.outbound.calendar import google_adapter

    monkeypatch.setattr(google_adapter, "_to_naive_utc",
                        lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None))
    entries = [world.FixtureCalendarEntry(summary="Hangout", day=1, start="18:00")]
    found = world.calendar_events(entries, "America/Chicago", datetime(2026, 11, 15, 0, 0), datetime(2026, 11, 16, 23, 0), NOW)
    assert found[0]["start_datetime"] == datetime(2026, 11, 15, 18, 0)      # "18:00 UTC", which displays as noon


async def test_hooks_use_the_fixture_only_while_one_is_set(monkeypatch):
    from agent_system.adapters.outbound import houston_events
    from agent_system.adapters.outbound.llm import tools

    async def live_fetch(self, limit=30):
        return ["live"]

    async def live_pull(session, user_id, time_min, time_max, google_calendar=None):
        return ["live"]

    monkeypatch.setattr(houston_events.HoustonEventsAdapter, "get_latest_events", live_fetch)
    monkeypatch.setattr(tools, "pull_google_events", live_pull)
    monkeypatch.setattr(world, "_installed", False)
    world.install_world_fixture_hook()
    adapter = houston_events.HoustonEventsAdapter.__new__(houston_events.HoustonEventsAdapter)
    window = (datetime(2000, 1, 1), datetime(2100, 1, 1))

    assert await adapter.get_latest_events() == ["live"]
    assert await tools.pull_google_events(None, "u", *window) == ["live"]

    tokens = world.set_world([world.FixtureEvent(title="Frozen", time="19:00")],
                             [world.FixtureCalendarEntry(summary="Frozen call", start="09:00")], "America/Chicago")
    try:
        assert [e.title for e in await adapter.get_latest_events()] == ["Frozen"]
        assert [e["title"] for e in await tools.pull_google_events(None, "u", *window)] == ["Frozen call"]
    finally:
        world.reset_world(tokens)
    assert await adapter.get_latest_events() == ["live"]


def test_any_of_mentions_accept_any_one_spelling():
    case = EvalCase(id="c", turns=["hi"], expect={"must_mention_any": ["6 PM", "6:00 PM", "18:00"]})
    (ok,) = score_mentions(case, "Your hangout is at 6:00 pm tomorrow.")
    assert ok.passed and ok.name == "mentions_any"
    (bad,) = score_mentions(case, "Your hangout is at noon.")
    assert not bad.passed and bad.tag == "incomplete_answer"


def test_the_incidents_suite_is_a_hard_gate_and_every_case_names_its_incident():
    suite = load_suite("incidents")
    assert suite.must_pass_all and suite.rubrics == []          # deterministic, so the gate needs no judge
    # every case names its incident and runs on frozen data, never the live network
    assert all(c.incident and (c.events_fixture or c.calendar_fixture or c.web_fixture) for c in suite.cases)

    result = lambda cid, ok: {"case_id": cid, "passed": ok, "scores": {}, "judgements": {}, "turns": [],  # noqa: E731
                              "failure_tags": [] if ok else ["incomplete_answer"], "total_ms": 1.0}
    clean = summarize(suite, [result("a", True), result("b", True)], [])
    assert clean["gate"] == {"rule": "every case must pass", "passed": True, "failed_cases": []}
    # 9 of 10 attempts passing is a 90% pass rate and still a failed gate
    flaky = summarize(suite, [result("a", True)] * 5 + [result("b", True)] * 4 + [result("b", False)], [])
    assert flaky["pass_rate"] == 0.9 and flaky["gate"]["passed"] is False and flaky["gate"]["failed_cases"] == ["b"]
    assert summarize(load_suite("routing"), [result("a", False)], [])["gate"] is None
