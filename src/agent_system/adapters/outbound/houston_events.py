"""Adapter for querying Houston events from htown_mania app."""

import logging
import os
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Internal K8s service URL (same cluster, houston-events namespace)
HTOWN_EVENTS_INTERNAL_URL = "http://houston-event-mania.houston-events.svc.cluster.local"
# External fallback
HTOWN_EVENTS_EXTERNAL_URL = "https://events.macdoncml.com"
# The service returns newest-first by insertion, not by date, and holds a few hundred
# records. Asking for 15 (as the tool used to) showed a quarter of one day.
FETCH_LIMIT = 500


class HoustonEvent(BaseModel):
    """Houston event from htown_mania."""
    
    id: int | None = None
    title: str
    description: str | None = None
    url: str | None = None
    location: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    categories: list[str] = []
    source: str | None = None


class HoustonEventsAdapter:
    """Adapter to fetch Houston events from htown_mania API."""
    
    def __init__(self, base_url: str | None = None):
        """Initialize the adapter.
        
        Args:
            base_url: Override the base URL (uses internal K8s URL by default)
        """
        self.base_url = base_url or os.environ.get(
            "HTOWN_EVENTS_URL",
            HTOWN_EVENTS_INTERNAL_URL
        )
        self._client: httpx.AsyncClient | None = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=30.0,
            )
        return self._client
    
    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    async def get_latest_events(self, limit: int = 30) -> list[HoustonEvent]:
        """Fetch the latest Houston events.
        
        Args:
            limit: Maximum number of events to return
            
        Returns:
            List of Houston events
        """
        try:
            client = await self._get_client()
            response = await client.get(f"/events/latest?limit={limit}")
            response.raise_for_status()
            
            events_data = response.json()
            events = [HoustonEvent(**e) for e in events_data]
            logger.info(f"Fetched {len(events)} Houston events from htown_mania")
            return events
            
        except httpx.ConnectError:
            # Try external URL as fallback
            logger.warning(f"Internal URL failed, trying external: {HTOWN_EVENTS_EXTERNAL_URL}")
            try:
                async with httpx.AsyncClient(timeout=30.0) as fallback_client:
                    response = await fallback_client.get(
                        f"{HTOWN_EVENTS_EXTERNAL_URL}/events/latest?limit={limit}"
                    )
                    response.raise_for_status()
                    events_data = response.json()
                    events = [HoustonEvent(**e) for e in events_data]
                    logger.info(f"Fetched {len(events)} Houston events via external URL")
                    return events
            except Exception as fallback_err:
                logger.error(f"External fallback also failed: {fallback_err}")
                return []
                
        except Exception as e:
            logger.error(f"Failed to fetch Houston events: {e}")
            return []
    
    async def search_events(
        self,
        query: str | None = None,
        category: str | None = None,
        limit: int = 20,
    ) -> list[HoustonEvent]:
        """Search Houston events with optional filters.
        
        Since the API only has /latest, we filter client-side.
        
        Args:
            query: Text to search in title/description
            category: Category to filter by (music, cycling, sports, etc.)
            limit: Maximum results to return
            
        Returns:
            Filtered list of events
        """
        # Get all recent events
        all_events = await self.get_latest_events(limit=FETCH_LIMIT)
        
        filtered = all_events
        
        # Filter by search query
        if query:
            query_lower = query.lower()
            filtered = [
                e for e in filtered
                if query_lower in (e.title or "").lower()
                or query_lower in (e.description or "").lower()
                or query_lower in (e.location or "").lower()
            ]
        
        # Filter by category
        if category:
            category_lower = category.lower()
            filtered = [
                e for e in filtered
                if any(category_lower in cat.lower() for cat in e.categories)
            ]
        
        return filtered[:limit]


HOUSTON_TZ = "America/Chicago"


def _houston_local(dt: datetime) -> datetime:
    """Event times come from the events service in UTC; readers are in Houston."""
    from datetime import timezone as _tz
    from zoneinfo import ZoneInfo

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tz.utc)
    return dt.astimezone(ZoneInfo(HOUSTON_TZ))


def houston_now() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(HOUSTON_TZ))


# ---------------------------------------------------------------------------
# Choosing which events to show
# ---------------------------------------------------------------------------

_EVENING_HOUR = 17
_WHEN_WORDS = (
    ("tonight", "tonight"), ("this evening", "tonight"), ("tomorrow", "tomorrow"),
    ("this weekend", "weekend"), ("weekend", "weekend"), ("next week", "next_week"),
    ("this week", "week"), ("today", "today"), ("right now", "today"), (" now", "today"),
)


def infer_when(text: str | None) -> str | None:
    """Pick a time window out of free text ("what's on tonight?" -> "tonight")."""
    lowered = f" {(text or '').lower()} "
    for phrase, window in _WHEN_WORDS:
        if phrase in lowered:
            return window
    return None


def window_for(when: str | None, now: datetime) -> tuple[Any, Any, bool]:
    """(first day, last day, evening only) in Houston time for a window name or an ISO date.

    Unknown or empty means "from today for a week": never the past.
    """
    from datetime import date, timedelta

    today = now.date()
    key = (when or "").strip().lower().replace(" ", "_")
    if key in ("today", "now"):
        return today, today, False
    if key == "tonight":
        return today, today, True
    if key == "tomorrow":
        return today + timedelta(days=1), today + timedelta(days=1), False
    if key in ("weekend", "this_weekend"):
        # Friday to Sunday; on a Saturday or Sunday, what is left of this one.
        friday = today + timedelta(days=(4 - today.weekday()) % 7) if today.weekday() < 5 else today
        sunday = today + timedelta(days=6 - today.weekday())
        return friday, sunday, False
    if key == "next_week":
        monday = today + timedelta(days=7 - today.weekday())
        return monday, monday + timedelta(days=6), False
    try:
        day = date.fromisoformat(key)
        return day, day, False
    except ValueError:
        return today, today + timedelta(days=6), False


_NOISE = {"the", "a", "an", "at", "in", "of", "and", "with", "w", "presents", "houston", "tx", "live", "festival",
          "saturday", "sunday", "friday", "monday", "tuesday", "wednesday", "thursday"}


def _tokens(text: str | None) -> set[str]:
    import re

    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if w not in _NOISE and not (w.isdigit() and len(w) == 4)}


def _same_event(a: HoustonEvent, b: HoustonEvent) -> bool:
    """Same day, same venue, and one title's words largely contained in the other's."""
    if not (a.start_time and b.start_time) or _houston_local(a.start_time).date() != _houston_local(b.start_time).date():
        return False
    va, vb = _tokens((a.location or "").split(",")[0]), _tokens((b.location or "").split(",")[0])
    if va and vb and not (va & vb):
        return False
    ta, tb = _tokens(a.title), _tokens(b.title)
    if not ta or not tb:
        return False
    return len(ta & tb) / min(len(ta), len(tb)) >= 0.75


def _is_ticketed(event: HoustonEvent) -> bool:
    return "ticketmaster" in (event.source or "").lower()


def _has_time(event: HoustonEvent) -> bool:
    """Date-only records arrive as midnight Houston time."""
    local = _houston_local(event.start_time)
    return (local.hour, local.minute) != (0, 0)


def _real_description(event: HoustonEvent) -> str | None:
    """Some sources put the venue name in the description; that is not a description."""
    text = (event.description or "").strip()
    if not text or _tokens(text) <= _tokens(event.location):
        return None
    return text


def merge_duplicates(events: list[HoustonEvent]) -> list[HoustonEvent]:
    """Collapse the same event listed by several sources (or several times by one).

    The ticketing source wins for time and link, since its times are the event's own;
    the longest real description and all categories are kept.
    """
    merged: list[HoustonEvent] = []
    for event in sorted(events, key=lambda e: (not _is_ticketed(e), -len(_real_description(e) or ""))):
        twin = next((m for m in merged if _same_event(m, event)), None)
        if twin is None:
            merged.append(event.model_copy(update={"description": _real_description(event)}))
            continue
        update: dict[str, Any] = {"categories": list(dict.fromkeys([*twin.categories, *event.categories]))}
        if not twin.description and _real_description(event):
            update["description"] = _real_description(event)
        if not _has_time(twin) and _has_time(event):
            update["start_time"] = event.start_time
        if not twin.url or ("google.com/search" in twin.url and event.url and "google.com/search" not in event.url):
            update["url"] = event.url or twin.url
        merged[merged.index(twin)] = twin.model_copy(update=update)
    return merged


def select_events(
    events: list[HoustonEvent],
    *,
    when: str | None = None,
    query: str | None = None,
    category: str | None = None,
    now: datetime | None = None,
    limit: int = 40,
) -> tuple[list[HoustonEvent], int]:
    """Events in the window, matching the text and category, de-duplicated, in time order.

    Returns (shown, total matched) so the caller can say how many were left out.
    """
    now = now or houston_now()
    first, last, evening = window_for(when, now)
    chosen = []
    for event in events:
        if not event.start_time:
            continue
        local = _houston_local(event.start_time)
        if not (first <= local.date() <= last):
            continue
        if evening and _has_time(event) and local.hour < _EVENING_HOUR:
            continue
        if query:
            q = query.lower()
            if not any(q in (field or "").lower() for field in (event.title, event.description, event.location)):
                continue
        if category and not any(category.lower() in c.lower() for c in event.categories):
            continue
        chosen.append(event)
    merged = merge_duplicates(chosen)
    merged.sort(key=lambda e: (_houston_local(e.start_time).date(), not _has_time(e), _houston_local(e.start_time)))
    return merged[:limit], len(merged)


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


def _part_of_day(event: HoustonEvent) -> str:
    if not _has_time(event):
        return "Time not listed"
    hour = _houston_local(event.start_time).hour
    return "Morning" if hour < 12 else "Afternoon" if hour < _EVENING_HOUR else "Evening"


def format_houston_events_for_display(events: list[HoustonEvent], total: int | None = None) -> str:
    """A listing grouped by day and time of day, with everything known about each event."""
    if not events:
        return "No Houston events found matching your criteria."

    lines = [f"## Houston Events ({len(events)} found)"]
    lines.append("_Times are Houston local._")
    if total and total > len(events):
        lines.append(f"_Showing {len(events)} of {total}; add a category, a search word or a narrower time to see the rest._")
    day = part = None
    for event in events:
        if event.start_time:
            local = _houston_local(event.start_time)
            if local.date() != day:
                day, part = local.date(), None
                lines.append(f"\n### {local.strftime('%A, %B %d')}")
            if _part_of_day(event) != part:
                part = _part_of_day(event)
                lines.append(f"\n**{part}**")
        title = f"[{event.title}]({event.url})" if event.url else event.title
        facts = []
        if event.start_time and _has_time(event):
            facts.append(_houston_local(event.start_time).strftime("%I:%M %p").lstrip("0"))
        if event.end_time:
            facts[-1:] = [f"{facts[-1]} to {_houston_local(event.end_time).strftime('%I:%M %p').lstrip('0')}"] if facts else []
        if event.location:
            facts.append(event.location)
        if event.categories:
            facts.append(", ".join(event.categories))
        lines.append(f"- **{title}** — {' · '.join(facts)}" if facts else f"- **{title}**")
        description = _real_description(event)
        if description:
            description = " ".join(description.split())
            lines.append(f"  {description[:400] + '...' if len(description) > 400 else description}")
    return "\n".join(lines)
