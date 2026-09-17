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
        all_events = await self.get_latest_events(limit=100)
        
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


def _houston_local(dt: datetime) -> datetime:
    """Event times come from the events service in UTC; readers are in Houston."""
    from datetime import timezone as _tz
    from zoneinfo import ZoneInfo

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tz.utc)
    return dt.astimezone(ZoneInfo("America/Chicago"))


def format_houston_events_for_display(events: list[HoustonEvent]) -> str:
    """Format Houston events for display in agent responses.
    
    Args:
        events: List of Houston events
        
    Returns:
        Formatted string for display with all available information
    """
    if not events:
        return "No Houston events found matching your criteria."
    
    lines = [f"## Houston Events ({len(events)} found)\n"]
    
    for i, event in enumerate(events, 1):
        # Title with link if available
        if event.url:
            lines.append(f"### {i}. [{event.title}]({event.url})")
        else:
            lines.append(f"### {i}. {event.title}")
        
        # Date/time formatting
        if event.start_time:
            start_str = _houston_local(event.start_time).strftime("%A, %B %d, %Y at %I:%M %p %Z")
            if event.end_time:
                # Same day? Just show end time
                if event.start_time.date() == event.end_time.date():
                    end_str = _houston_local(event.end_time).strftime("%I:%M %p")
                    lines.append(f"📅 **When:** {start_str} - {end_str}")
                else:
                    end_str = _houston_local(event.end_time).strftime("%A, %B %d at %I:%M %p")
                    lines.append(f"📅 **When:** {start_str} - {end_str}")
            else:
                lines.append(f"📅 **When:** {start_str}")
        
        # Location
        if event.location:
            lines.append(f"📍 **Where:** {event.location}")
        
        # Categories
        if event.categories:
            cats = ", ".join(event.categories)
            lines.append(f"🏷️ **Categories:** {cats}")
        
        # Source
        if event.source:
            lines.append(f"📰 **Source:** {event.source}")
        
        # Description
        if event.description:
            # Truncate very long descriptions but keep useful info
            desc = event.description.strip()
            if len(desc) > 500:
                desc = desc[:500] + "..."
            lines.append(f"\n> {desc}")
        
        # Direct link (shown separately for easy copying)
        if event.url:
            lines.append(f"\n🔗 **Tickets/Info:** {event.url}")
        
        lines.append("")  # Blank line between events
        lines.append("---")  # Separator
        lines.append("")
    
    return "\n".join(lines)
