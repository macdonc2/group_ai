"""Showing a place on a map in the chat.

The model never writes a map URL. It names a place; `show_map` validates the name and builds
the link in code; the turn then makes sure that exact link is in the reply (`with_map_links`).
The chat UI recognises the link's fixed shape and draws an embedded map under the message,
taking only the place text from it, so nothing the model writes can choose what the frame loads.

No geocoding and no key: the map provider resolves the place text itself. The cost of that
choice is that this code cannot tell whether the place exists or which of two same-named places
the map will show, so the tool result tells the model not to state an address it was not given.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlsplit

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

MAP_LINK_PREFIX = "https://www.google.com/maps/search/?api=1&query="
MAX_PLACE_CHARS = 200
MAX_MAPS_PER_REPLY = 3

_MAP_LINK = re.compile(re.escape(MAP_LINK_PREFIX) + r"[^\s)>\]\"'<]+")
_VAGUE = {"it", "there", "here", "that", "this", "that place", "this place", "the place", "the venue", "home"}


class MapPlace(BaseModel):
    """A place the map can be asked for: plain text, one line, a name or address and not a link."""

    model_config = ConfigDict(frozen=True)

    place: str
    near: str | None = None

    @field_validator("place", "near")
    @classmethod
    def _plain_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(str(value).split())
        if not value:
            return None
        if len(value) > MAX_PLACE_CHARS:
            raise ValueError(f"longer than {MAX_PLACE_CHARS} characters")
        if re.search(r"https?://|www\.", value, re.IGNORECASE):
            raise ValueError("a link, not a place name or address")
        if not any(ch.isalnum() for ch in value):
            raise ValueError("no letters or digits")
        return value

    @field_validator("place")
    @classmethod
    def _concrete(cls, value: str | None) -> str:
        if not value or len(value) < 2:
            raise ValueError("empty")
        if value.lower() in _VAGUE:
            raise ValueError("not a concrete place; give its name or address")
        return value

    @property
    def query(self) -> str:
        """What the map is asked for. `near` is added unless the place text already says it."""
        if self.near and self.near.lower() not in self.place.lower():
            return f"{self.place}, {self.near}"
        return self.place

    @property
    def link(self) -> str:
        return MAP_LINK_PREFIX + quote_plus(self.query)


def map_query(link: str) -> str | None:
    """The place text inside a map link of our shape, or None for any other URL."""
    if not link.startswith(MAP_LINK_PREFIX):
        return None
    values = parse_qs(urlsplit(link).query).get("query")
    return " ".join(values[0].split()) if values and values[0].strip() else None


def map_links_in(text: str) -> list[str]:
    """Map links of our shape in `text`, in order, trailing punctuation removed."""
    return [m.group(0).rstrip(".,;:!?") for m in _MAP_LINK.finditer(text or "")]


def with_map_links(reply: str, links: list[str]) -> str:
    """`reply`, with a line added for each of `links` whose place it does not already link to.

    Links are compared by place text, so the model re-encoding the same link is not a miss.
    """
    have = {(map_query(u) or "").lower() for u in map_links_in(reply)}
    lines: list[str] = []
    for link in links[:MAX_MAPS_PER_REPLY]:
        query = map_query(link)
        if not query or query.lower() in have:
            continue
        have.add(query.lower())
        label = query.replace("[", "(").replace("]", ")")
        lines.append(f"[{label} on Google Maps]({link})")
    if not lines:
        return reply
    return reply.rstrip() + "\n\n" + "\n\n".join(lines)


async def show_map(place: str, near: str | None = None) -> Any:
    """Validate a place and build its map link. Makes no network call. Returns a ToolResult."""
    from agent_system.adapters.outbound.llm.tools import ToolResult

    try:
        target = MapPlace(place=place, near=near)
    except ValidationError as exc:
        reason = "; ".join(str(e["msg"]).removeprefix("Value error, ") for e in exc.errors())
        return ToolResult(success=False, data=None, message=f"Cannot map {place!r}: {reason}.")
    data: dict[str, Any] = {"query": target.query, "url": target.link}
    return ToolResult(
        success=True, data=data,
        message=(f"A map of \"{target.query}\" will be shown under your reply, with this link: {target.link}\n"
                 "The map service finds the place from that text; this tool did not confirm the place exists or "
                 "look up its address. Say where it is only as far as you know or a tool told you, and do not "
                 "state a street address you were not given."),
    )
