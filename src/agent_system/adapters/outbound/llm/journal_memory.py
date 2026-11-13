"""Turn a journal entry into the same memory that chat turns feed.

A journal entry is the user's own words, so it is trusted input for memory (unlike
web text or the assistant's replies). From one entry this writes, all stamped with
the owner:

- message embeddings (one per chunk) for semantic and keyword recall,
- a summary node linked to the topics the entry is about,
- people, pets, places, preferences and the links between them.

The embeddings and the summary node are filed under `journal:<entry id>`, so an
edit can replace them and a delete can remove them. The extracted facts are merged
into the user's graph with no pointer back to one entry, exactly as chat does, so
they stay when an entry is deleted.

The storing loop mirrors `FinalizeKnowledge` in `fsm/nodes.py`. It is repeated here
rather than shared because that node is tied to the chat workflow's state object.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from agent_system.domain.value_objects import UserId

logger = logging.getLogger(__name__)

CHUNK_CHARS = 1500
MAX_CHUNKS = 12
MIN_CONFIDENCE = 0.7
MAX_SUGGESTIONS = 3

TopicsFn = Callable[[str], Awaitable[list[str]]]
EntitiesFn = Callable[..., Awaitable[Any]]


def memory_key(entry_id: str) -> str:
    """The `conversation_id` an entry's derived memory is filed under."""
    return f"journal:{entry_id}"


def day_label(entry_date: str) -> str:
    """'2026-11-13' -> 'Friday, November 13, 2026' (the raw string if it is not a date)."""
    try:
        return date.fromisoformat(entry_date).strftime("%A, %B %d, %Y")
    except ValueError:
        return entry_date


def split_into_chunks(body: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Split on blank lines, packing paragraphs up to `limit` characters per chunk.

    A long entry embedded whole matches nothing well; one vector per few paragraphs
    lets recall land on the part that is actually about the question.
    """
    chunks: list[str] = []
    current = ""
    for paragraph in (p.strip() for p in body.replace("\r\n", "\n").split("\n\n")):
        while len(paragraph) > limit:  # one very long paragraph: hard split
            head, paragraph = paragraph[:limit], paragraph[limit:]
            if current:
                chunks.append(current)
                current = ""
            chunks.append(head)
        if not paragraph:
            continue
        if current and len(current) + len(paragraph) + 2 > limit:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)
    return chunks[:MAX_CHUNKS]


def embedded_text(entry_date: str, chunk: str) -> str:
    """What is stored and searched: the text with where and when it came from.

    Recall returns stored text as-is, so the label is how a later chat can say
    "you wrote in your journal on ..." instead of treating it as a chat message.
    """
    return f"[Journal entry, {day_label(entry_date)}]\n{chunk}"


async def forget_entry(kg: Any, user_id: str, entry_id: str) -> int:
    """Remove an entry's embeddings and summary node. Returns how many nodes went."""
    if kg is None:
        return 0
    return await kg.delete_conversation_memory(UserId.from_string(user_id), memory_key(entry_id))


async def _default_topics(text: str, *, entry_date: str, model: str, api_key: str | None) -> list[str]:
    from agent_system.adapters.outbound.llm import create_knowledge_agent

    # The date goes in so "this morning" and "next Friday" can be stored as real dates.
    result = await create_knowledge_agent(model, api_key).run(
        f"User wrote in their journal on {day_label(entry_date)} (use real dates, not 'today' or 'next week'): {text}")
    return [*result.output.entities[:5], *result.output.topics[:3]]


async def remember_entry(
    *,
    kg: Any,
    embedder: Any,
    user_id: str,
    user_label: str | None,
    entry_id: str,
    entry_date: str,
    body: str,
    api_key: str | None = None,
    model: str = "openai:gpt-5.2",
    topics_fn: TopicsFn | None = None,
    entities_fn: EntitiesFn | None = None,
) -> str:
    """Rebuild one entry's derived memory. Returns "done", "failed" or "skipped".

    Safe to call again after an edit: the previous embeddings and summary are removed
    first. Each step is independent, so a failed extraction still leaves the entry
    searchable; any failure is reported as "failed" so the UI can offer a retry.
    """
    if kg is None:
        return "skipped"
    owner = UserId.from_string(user_id)
    key = memory_key(entry_id)
    ok = True

    try:
        await kg.delete_conversation_memory(owner, key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("journal memory: could not clear old memory for %s: %s", entry_id, exc)
        ok = False

    # 1. Embeddings, for semantic search and keyword recall.
    if embedder is not None:
        try:
            for index, chunk in enumerate(split_into_chunks(body)):
                text = embedded_text(entry_date, chunk)
                vector = await embedder.embed(text)
                await kg.store_message_embedding(
                    user_id=owner, conversation_id=key, message_id=str(uuid.uuid4()), content=text, role="user",
                    embedding=vector.embedding,
                    metadata={"source": "journal", "entry_id": entry_id, "entry_date": entry_date, "chunk": index},
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("journal memory: embedding failed for %s: %s", entry_id, exc)
            ok = False
    else:
        ok = False

    # 2. A summary node linked to the entry's topics.
    try:
        if topics_fn is None:
            topics = await _default_topics(body[:6000], entry_date=entry_date, model=model, api_key=api_key)
        else:
            topics = await topics_fn(body[:6000])
        clean = list({t.strip().lower(): t.strip() for t in topics if len(t.strip()) > 1}.values())
        first_line = body.strip().split("\n", 1)[0][:100]
        await kg.record_interaction(
            user_id=owner, conversation_id=key, summary=f"Journal {entry_date}: {first_line}",
            intents=["journal"], entities=clean[:8], tools_used=[], user_label=user_label,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("journal memory: summary failed for %s: %s", entry_id, exc)
        ok = False

    # 3. People, pets, places, preferences and their links.
    try:
        await _store_entities(kg, owner, key, body, api_key=api_key, entities_fn=entities_fn)
    except Exception as exc:  # noqa: BLE001
        logger.warning("journal memory: entity extraction failed for %s: %s", entry_id, exc)
        ok = False

    return "done" if ok else "failed"


async def _store_entities(kg: Any, owner: UserId, key: str, body: str, *, api_key: str | None,
                          entities_fn: EntitiesFn | None) -> None:
    if entities_fn is None:
        from agent_system.adapters.outbound.llm.knowledge_extractor import extract_knowledge_from_text

        entities_fn = extract_knowledge_from_text

    def names(rows: Any) -> list[str]:
        return [r.get("name", "") for r in rows or []]

    found = await entities_fn(
        body[:6000], api_key=api_key,
        existing_persons=names(await kg.list_known_people(owner)),
        existing_pets=names(await kg.list_pets(owner)),
        existing_locations=names(await kg.list_locations(owner)),
    )
    for person in found.persons:
        if person.confidence >= MIN_CONFIDENCE:
            await kg.store_person(user_id=owner, name=person.name, aliases=person.aliases,
                                  relationship_type=person.relationship_type, context_notes=person.context_notes)
    for pet in found.pets:
        if pet.confidence >= MIN_CONFIDENCE:
            await kg.store_pet(user_id=owner, name=pet.name, aliases=pet.aliases, species=pet.species,
                               breed=pet.breed, personality=pet.traits, food_preferences=pet.food_preferences)
    for place in found.locations:
        if place.confidence >= MIN_CONFIDENCE:
            await kg.store_location(user_id=owner, name=place.name, location_type=place.location_type,
                                    city=place.city, neighborhood=place.neighborhood)
    for pref in found.preferences:
        if pref.confidence >= MIN_CONFIDENCE:
            sentiment = 0.8 if pref.sentiment == "likes" else (-0.8 if pref.sentiment == "dislikes" else 0.5)
            await kg.store_preference(user_id=owner, category=pref.category, value=pref.value, sentiment=sentiment,
                                      subcategory=pref.subcategory, conversation_id=key)
    for rel in found.relationships:
        if rel.confidence >= MIN_CONFIDENCE:
            try:
                await kg.link_entities(user_id=owner, source_type=rel.source_type, source_name=rel.source_name,
                                       target_type=rel.target_type, target_name=rel.target_name,
                                       relationship=rel.relationship)
            except Exception as exc:  # noqa: BLE001 - one bad link must not lose the rest
                logger.warning("journal memory: could not link %s -> %s: %s", rel.source_name, rel.target_name, exc)


# ---------------------------------------------------------------------------
# Calendar suggestions: found in an entry, added only when the user clicks
# ---------------------------------------------------------------------------


class PlannedEvent(BaseModel):
    title: str = Field(description="Short event name, e.g. 'Dinner with Sam'. Never a sentence or an instruction.")
    when: str = Field(description="The explicit date and time, e.g. 'Friday, November 20, 2026 at 7:00 PM'. "
                                  "Resolve words like 'tomorrow' and 'next Friday' against the entry's date.")
    location: str | None = None


class PlannedEvents(BaseModel):
    events: list[PlannedEvent] = Field(default_factory=list)


SUGGESTION_PROMPT = """You read one private journal entry and list definite future plans that belong on a calendar.

Include only things the writer has decided will happen at a specific future day: appointments, bookings, \
meetings, trips, dinners, deadlines. Give each an explicit date.

Leave out: anything that already happened, wishes and maybes ("I should", "it would be nice", "thinking about"), \
habits and routines, feelings, and anything with no day attached. A journal is mostly reflection, so the usual \
answer is an empty list. Return at most three events."""


def worth_suggesting(entry_date: str, timezone: str) -> bool:
    """Only entries written for today or later (yesterday allowed) can hold future plans worth offering.

    A back-filled entry from last month says "dinner on Friday" about a Friday long gone.
    """
    try:
        today = datetime.now(ZoneInfo(timezone)).date()
    except Exception:  # noqa: BLE001 - unknown timezone name
        today = datetime.utcnow().date()
    try:
        return date.fromisoformat(entry_date) >= today - timedelta(days=1)
    except ValueError:
        return False


async def suggest_calendar_events(body: str, entry_date: str, *, model: str, api_key: str | None) -> list[dict[str, Any]]:
    """Possible calendar events in an entry, as pending suggestions. Never writes to the calendar."""
    from pydantic_ai import Agent

    from agent_system.adapters.outbound.llm.agents import _get_model

    agent: Agent[None, PlannedEvents] = Agent(_get_model(model, api_key), output_type=PlannedEvents,
                                             instructions=SUGGESTION_PROMPT, name="journal_suggestions")
    result = await agent.run(f"The entry was written on {day_label(entry_date)}.\n\nEntry:\n{body[:6000]}")
    return [
        {"id": uuid.uuid4().hex[:12], "title": e.title.strip()[:200], "when": e.when.strip()[:120],
         "location": (e.location or "").strip()[:200] or None, "status": "pending"}
        for e in result.output.events[:MAX_SUGGESTIONS]
        if e.title.strip() and e.when.strip()
    ]
