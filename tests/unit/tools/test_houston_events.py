"""Choosing and showing Houston events: time windows, duplicates, and the listing format."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from agent_system.adapters.outbound.houston_events import (
    HoustonEvent,
    format_houston_events_for_display,
    infer_when,
    merge_duplicates,
    select_events,
    window_for,
)

pytestmark = pytest.mark.unit

CT = ZoneInfo("America/Chicago")
NOW = datetime(2026, 11, 14, 9, 30, tzinfo=CT)  # a Saturday morning in Houston


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=CT).astimezone(timezone.utc)


def event(title, start, *, venue="Shell Energy Stadium, Houston", source="Ticketmaster", description=None,
          url="https://www.ticketmaster.com/event/x", categories=("music",)):
    return HoustonEvent(title=title, start_time=start, location=venue, source=source, description=description,
                        url=url, categories=list(categories))


GOOGLE = dict(source="Google Events (SerpAPI)", url="https://www.google.com/search?q=x")


def test_time_words_become_windows():
    assert infer_when("What's going on in h-town now?") == "today"
    assert infer_when("any concerts tonight") == "tonight"
    assert infer_when("things to do this weekend") == "weekend"
    assert infer_when("more details on the Breakaway festival") is None

    sat = NOW.date()
    assert window_for("today", NOW) == (sat, sat, False)
    assert window_for("tonight", NOW) == (sat, sat, True)
    assert window_for("weekend", NOW)[:2] == (sat, sat.replace(day=15))  # what is left of it
    assert window_for("2026-11-20", NOW)[:2] == (sat.replace(day=20),) * 2
    assert window_for(None, NOW)[:2] == (sat, sat.replace(day=20))  # a week ahead, never the past


def test_today_means_today_in_houston_not_the_newest_records():
    events = [
        event("Yesterday's Show", at(13, 20)),
        event("Morning Market", at(14, 9), venue="POST Houston"),
        event("Late Show", at(14, 23), venue="Scout Bar"),          # 05:00 UTC on the 15th
        event("Tomorrow Brunch", at(15, 11), venue="Montrose"),
    ]
    shown, total = select_events(events, when="today", now=NOW)
    assert [e.title for e in shown] == ["Morning Market", "Late Show"] and total == 2
    tonight, _ = select_events(events, when="tonight", now=NOW)
    assert [e.title for e in tonight] == ["Late Show"]


def test_the_same_event_from_several_sources_is_listed_once():
    # What production held for one festival: four records, three different times.
    events = [
        event("Breakaway Houston 2026", at(14, 15), description="Shell Energy Stadium", categories=("community",), **GOOGLE),
        event("2026 Breakaway Music Festival Houston: Saturday", at(14, 16), description="Shell Energy Stadium", **GOOGLE),
        event("Breakaway Music Festival", at(14, 0), description="Shell Energy Stadium", **GOOGLE),   # date only
        event("Breakaway Music Festival", at(14, 12), venue="Shell Energy Stadium, Houston"),
        event("Leanne Morgan", at(14, 19), venue="Toyota Center - TX, Houston"),
    ]
    merged = merge_duplicates(events)
    assert sorted(e.title for e in merged) == ["Breakaway Music Festival", "Leanne Morgan"]
    festival = next(e for e in merged if e.title.startswith("Breakaway"))
    assert festival.start_time == at(14, 12)                       # the ticketing source's time
    assert "ticketmaster.com" in festival.url                      # and its link, not a Google search
    assert festival.description is None                            # a venue name is not a description
    assert set(festival.categories) == {"music", "community"}


def test_different_events_at_one_venue_stay_separate():
    events = [
        event("Houston Holiday Market", at(14, 11), venue="POST Houston, Houston, TX", **GOOGLE),
        event("BARC Adoption Day", at(14, 11), venue="POST Houston, Houston, TX", **GOOGLE),
    ]
    assert len(merge_duplicates(events)) == 2


def test_listing_is_grouped_by_day_and_time_and_keeps_real_descriptions():
    events = [
        event("Morning Market", at(14, 9), venue="POST Houston", description="Makers and food trucks."),
        event("Buena Vista Orchestra", at(14, 19), venue="House of Blues Houston", description="DOORS: 7:00 PM All Ages"),
        event("Sunday Ride", at(15, 0), venue="Memorial Park", url=None, categories=("cycling",)),
    ]
    shown, total = select_events(events, when="weekend", now=NOW)
    text = format_houston_events_for_display(shown, total)
    assert text.startswith("## Houston Events (3 found)")           # the FSM detects listings by this header
    assert text.index("### Saturday, November 14") < text.index("**Morning**") < text.index("**Evening**")
    assert "- **[Morning Market](https://www.ticketmaster.com/event/x)** — 9:00 AM · POST Houston · music" in text
    assert "  Makers and food trucks." in text
    assert "### Sunday, November 15" in text and "**Time not listed**" in text
    assert "- **Sunday Ride** — Memorial Park · cycling" in text    # no invented midnight start


def test_a_long_day_says_how_much_was_left_out():
    events = [event(f"Show {i}", at(14, 10 + i % 10, i), venue=f"Venue {i}") for i in range(50)]
    shown, total = select_events(events, when="today", now=NOW, limit=40)
    assert (len(shown), total) == (40, 50)
    assert "_Showing 40 of 50;" in format_houston_events_for_display(shown, total)
