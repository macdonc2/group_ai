"""Journal API: dated entries, the calendar of days, calendar suggestions and the side chat.

Access control: every route takes the signed-in user from the token and every query
is filtered by that user id inside the repository. Someone else's entry is reported
as 404, the same as one that does not exist, so ids cannot be probed.

Memory: saving or editing an entry returns at once; the graph and vector memory are
rebuilt in a background task (`process_entry`). Postgres stays the source of truth,
so a failed memory write never loses writing, and the entry shows its memory state.
"""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent_system.adapters.inbound.api.dependencies import CurrentUserId, SessionDep, get_database
from agent_system.adapters.inbound.api.schemas import StreamEvent
from agent_system.adapters.outbound.persistence import SQLAlchemyUserRepository
from agent_system.adapters.outbound.persistence.journal_models import JournalEntryModel, JournalMessageModel
from agent_system.adapters.outbound.persistence.journal_repository import SQLAlchemyJournalRepository
from agent_system.domain.value_objects import UserId

router = APIRouter(prefix="/journal", tags=["journal"])
logger = logging.getLogger(__name__)

MAX_ENTRY_CHARS = 20_000
MAX_MESSAGE_CHARS = 4_000
_EARLIEST_DAY = date(2000, 1, 1)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class EntryCreate(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_ENTRY_CHARS)
    date: str | None = Field(default=None, description="YYYY-MM-DD; defaults to today in the user's timezone")


class EntryUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_ENTRY_CHARS)


class SuggestionRead(BaseModel):
    id: str
    title: str
    when: str
    location: str | None = None
    status: str


class EntryRead(BaseModel):
    id: str
    date: str
    body: str
    memory_status: str
    suggestions: list[SuggestionRead]
    created_at: str
    updated_at: str


class DaysRead(BaseModel):
    today: str
    timezone: str
    month: str
    days: dict[str, int]


class MessageRead(BaseModel):
    id: str
    role: str
    content: str
    tools_used: list[str]
    created_at: str


class ChatRequest(BaseModel):
    date: str
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


def _utc_iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat() + "Z"  # stored as naive UTC


def _entry_read(entry: JournalEntryModel) -> EntryRead:
    return EntryRead(
        id=entry.id, date=entry.entry_date, body=entry.body, memory_status=entry.memory_status,
        suggestions=[SuggestionRead(**s) for s in (entry.suggestions or []) if s.get("status") != "dismissed"],
        created_at=_utc_iso(entry.created_at), updated_at=_utc_iso(entry.updated_at),
    )


def _message_read(message: JournalMessageModel) -> MessageRead:
    return MessageRead(id=message.id, role=message.role, content=message.content,
                       tools_used=list(message.tools_used or []), created_at=_utc_iso(message.created_at))


# ---------------------------------------------------------------------------
# Days and dates
# ---------------------------------------------------------------------------


def _today(timezone: str) -> date:
    """Today as the user sees it. Their timezone setting decides which day an entry belongs to."""
    try:
        return datetime.now(ZoneInfo(timezone or "UTC")).date()
    except Exception:  # noqa: BLE001 - an unknown timezone name falls back to UTC
        return datetime.utcnow().date()


def _valid_day(value: str, today: date) -> str:
    """A real day, not before 2000 and not after tomorrow (a journal records, it does not schedule)."""
    try:
        day = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD") from None
    if day.isoformat() != value or day < _EARLIEST_DAY or day > today + timedelta(days=1):
        raise HTTPException(status_code=422, detail="date is out of range")
    return value


async def _user(session: Any, user_id: str) -> Any:
    user = await SQLAlchemyUserRepository(session).get(UserId.from_string(user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def _local_time(value: datetime, timezone: str) -> str:
    try:
        return value.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(timezone or "UTC")).strftime("%I:%M %p")
    except Exception:  # noqa: BLE001
        return value.strftime("%H:%M UTC")


@router.get("/days")
async def list_days(
    current_user_id: CurrentUserId,
    session: SessionDep,
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$", description="YYYY-MM; defaults to the current month"),
) -> DaysRead:
    """Which days of a month have entries (for marking the calendar), plus the user's "today"."""
    user = await _user(session, current_user_id)
    today = _today(user.timezone)
    month = month or today.strftime("%Y-%m")
    try:
        first = date.fromisoformat(f"{month}-01")
    except ValueError:
        raise HTTPException(status_code=422, detail="month must be YYYY-MM") from None
    days = await SQLAlchemyJournalRepository(session).day_counts(current_user_id, first.isoformat(), f"{month}-31")
    return DaysRead(today=today.isoformat(), timezone=user.timezone or "UTC", month=month, days=days)


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------


@router.get("/entries")
async def list_entries(current_user_id: CurrentUserId, session: SessionDep,
                       date: str = Query(..., description="YYYY-MM-DD")) -> list[EntryRead]:
    user = await _user(session, current_user_id)
    day = _valid_day(date, _today(user.timezone))
    return [_entry_read(e) for e in await SQLAlchemyJournalRepository(session).entries_for_day(current_user_id, day)]


@router.post("/entries", status_code=status.HTTP_201_CREATED)
async def create_entry(payload: EntryCreate, current_user_id: CurrentUserId, session: SessionDep) -> EntryRead:
    user = await _user(session, current_user_id)
    today = _today(user.timezone)
    day = _valid_day(payload.date, today) if payload.date else today.isoformat()
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="An entry needs some text")
    entry = await SQLAlchemyJournalRepository(session).create_entry(current_user_id, day, body)
    await session.commit()  # the background task reads the row from its own session
    schedule_memory(entry.id, current_user_id)
    return _entry_read(entry)


@router.put("/entries/{entry_id}")
async def update_entry(entry_id: str, payload: EntryUpdate, current_user_id: CurrentUserId,
                       session: SessionDep) -> EntryRead:
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="An entry needs some text")
    repo = SQLAlchemyJournalRepository(session)
    entry = await repo.get_entry(entry_id, current_user_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")
    if body != entry.body:
        # Events already added stay listed; open suggestions belonged to the old text.
        kept = [s for s in (entry.suggestions or []) if s.get("status") == "added"]
        entry = await repo.update_entry(entry_id, current_user_id, body=body, memory_status="pending", suggestions=kept)
        await session.commit()
        schedule_memory(entry_id, current_user_id)
    return _entry_read(entry)


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(entry_id: str, current_user_id: CurrentUserId, session: SessionDep) -> None:
    """Delete an entry, its embeddings and its summary node. Facts already learned from it stay."""
    if not await SQLAlchemyJournalRepository(session).delete_entry(entry_id, current_user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")
    await session.commit()
    # Runs after any in-flight memory write for this entry, and finds the row gone.
    schedule_memory(entry_id, current_user_id)


@router.post("/entries/{entry_id}/remember", status_code=status.HTTP_202_ACCEPTED)
async def retry_memory(entry_id: str, current_user_id: CurrentUserId, session: SessionDep) -> EntryRead:
    """Rebuild an entry's memory (the retry button shown when it failed)."""
    entry = await SQLAlchemyJournalRepository(session).update_entry(entry_id, current_user_id, memory_status="pending")
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")
    await session.commit()
    schedule_memory(entry_id, current_user_id)
    return _entry_read(entry)


# ---------------------------------------------------------------------------
# Calendar suggestions: nothing reaches Google Calendar without a click
# ---------------------------------------------------------------------------


async def _suggestion(repo: SQLAlchemyJournalRepository, entry_id: str, suggestion_id: str,
                      user_id: str) -> tuple[JournalEntryModel, dict[str, Any]]:
    entry = await repo.get_entry(entry_id, user_id)
    found = next((s for s in (entry.suggestions if entry else None) or [] if s.get("id") == suggestion_id), None)
    if entry is None or found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found")
    return entry, found


def _with_status(entry: JournalEntryModel, suggestion_id: str, new_status: str) -> list[dict[str, Any]]:
    # A new list, so SQLAlchemy sees the JSON column change.
    return [{**s, "status": new_status} if s.get("id") == suggestion_id else dict(s) for s in entry.suggestions or []]


@router.post("/entries/{entry_id}/suggestions/{suggestion_id}/accept")
async def accept_suggestion(entry_id: str, suggestion_id: str, current_user_id: CurrentUserId,
                            session: SessionDep) -> EntryRead:
    """Add a suggested event to the user's Google Calendar. The click is the user's request."""
    repo = SQLAlchemyJournalRepository(session)
    entry, suggestion = await _suggestion(repo, entry_id, suggestion_id, current_user_id)
    if suggestion.get("status") == "added":
        return _entry_read(entry)  # a double click must not create the event twice
    result = await add_event(title=suggestion["title"], when=suggestion["when"], location=suggestion.get("location"),
                             description="Added from your journal.", session=session, user_id=current_user_id)
    if not getattr(result, "success", False):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=str(getattr(result, "message", "") or "The event could not be added."))
    entry = await repo.update_entry(entry_id, current_user_id, suggestions=_with_status(entry, suggestion_id, "added"))
    return _entry_read(entry)


@router.post("/entries/{entry_id}/suggestions/{suggestion_id}/dismiss")
async def dismiss_suggestion(entry_id: str, suggestion_id: str, current_user_id: CurrentUserId,
                             session: SessionDep) -> EntryRead:
    repo = SQLAlchemyJournalRepository(session)
    entry, suggestion = await _suggestion(repo, entry_id, suggestion_id, current_user_id)
    if suggestion.get("status") == "pending":
        entry = await repo.update_entry(entry_id, current_user_id,
                                        suggestions=_with_status(entry, suggestion_id, "dismissed"))
    return _entry_read(entry)


async def add_event(**kwargs: Any) -> Any:
    """The same calendar write the chat tool uses (a seam for tests)."""
    from agent_system.adapters.outbound.llm.tools import add_to_calendar

    return await add_to_calendar(**kwargs)


# ---------------------------------------------------------------------------
# Background memory work
# ---------------------------------------------------------------------------

_tasks: set[asyncio.Task] = set()
_locks: dict[str, asyncio.Lock] = {}  # one memory write per entry at a time, in this process


def schedule_memory(entry_id: str, user_id: str) -> None:
    task = asyncio.get_running_loop().create_task(process_entry(entry_id, user_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _api_key(user: Any, settings: Any) -> str | None:
    """System key first, else the user's own. Never touches os.environ."""
    if settings.openai_api_key:
        return settings.openai_api_key
    if user.has_api_key():
        from agent_system.domain.utils.encryption import get_api_key_encryption

        return get_api_key_encryption().decrypt(user.encrypted_openai_api_key)
    return None


async def _memory_ports(api_key: str | None) -> tuple[Any, Any]:
    from agent_system.composition_root.container import get_container

    container = await get_container()
    embedder = container.embedding_adapter
    if embedder is None and api_key:
        from agent_system.adapters.outbound.embedding import OpenAIEmbeddingAdapter

        embedder = OpenAIEmbeddingAdapter(api_key=api_key)
    return container.knowledge_graph_adapter, embedder


async def process_entry(entry_id: str, user_id: str) -> None:
    """Bring an entry's derived memory in line with its current text. Never raises.

    Always works from the row as it is now, under a per-entry lock: after a quick
    edit the second run sees the final text, and after a delete it finds no row and
    removes what the first run stored.
    """
    from agent_system.adapters.outbound.llm import journal_memory
    from agent_system.composition_root.config import get_settings

    async with _locks.setdefault(entry_id, asyncio.Lock()):
        try:
            settings = get_settings()
            database = get_database()
            async with database.session() as session:
                entry = await SQLAlchemyJournalRepository(session).get_entry(entry_id, user_id)
                user = await SQLAlchemyUserRepository(session).get(UserId.from_string(user_id))
            api_key = _api_key(user, settings) if user else None
            kg, embedder = await _memory_ports(api_key)
            if entry is None or user is None:
                await journal_memory.forget_entry(kg, user_id, entry_id)
                _locks.pop(entry_id, None)
                return

            body, day = entry.body, entry.entry_date
            memory_status = await journal_memory.remember_entry(
                kg=kg, embedder=embedder, user_id=user_id, user_label=user.email, entry_id=entry_id,
                entry_date=day, body=body, api_key=api_key, model=settings.default_model,
            )

            suggestions: list[dict[str, Any]] | None = None
            if api_key and user.has_google_calendar_connected() and journal_memory.worth_suggesting(day, user.timezone):
                try:
                    suggestions = await journal_memory.suggest_calendar_events(
                        body, day, model=settings.default_model, api_key=api_key)
                except Exception as exc:  # noqa: BLE001 - suggestions are a convenience
                    logger.warning("journal: calendar suggestions failed for %s: %s", entry_id, exc)

            async with database.session() as session:
                repo = SQLAlchemyJournalRepository(session)
                current = await repo.get_entry(entry_id, user_id)
                if current is not None and current.body == body:  # edited meanwhile: the next run owns it
                    fields: dict[str, Any] = {"memory_status": memory_status}
                    if suggestions is not None:
                        added = [s for s in (current.suggestions or []) if s.get("status") == "added"]
                        taken = {s["title"].lower() for s in added}
                        fields["suggestions"] = added + [s for s in suggestions if s["title"].lower() not in taken]
                    await repo.update_entry(entry_id, user_id, **fields)
                    await session.commit()
        except Exception:  # noqa: BLE001 - background work; the entry itself is already saved
            logger.exception("journal: memory update failed for entry %s", entry_id)
            try:
                async with get_database().session() as session:
                    await SQLAlchemyJournalRepository(session).update_entry(entry_id, user_id, memory_status="failed")
                    await session.commit()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Side chat
# ---------------------------------------------------------------------------


@router.get("/chat")
async def list_chat(current_user_id: CurrentUserId, session: SessionDep,
                    date: str = Query(..., description="YYYY-MM-DD")) -> list[MessageRead]:
    user = await _user(session, current_user_id)
    day = _valid_day(date, _today(user.timezone))
    return [_message_read(m) for m in await SQLAlchemyJournalRepository(session).messages_for_day(current_user_id, day)]


@router.delete("/chat", status_code=status.HTTP_204_NO_CONTENT)
async def clear_chat(current_user_id: CurrentUserId, session: SessionDep,
                     date: str = Query(..., description="YYYY-MM-DD")) -> None:
    user = await _user(session, current_user_id)
    day = _valid_day(date, _today(user.timezone))
    await SQLAlchemyJournalRepository(session).clear_messages(current_user_id, day)


@asynccontextmanager
async def _own_session() -> AsyncGenerator[Any, None]:
    async with get_database().session() as session:
        yield session


async def run_turn(message: str, *, deps: Any, api_key: str, history: list[Any]) -> Any:
    """One side-chat turn (a seam for tests)."""
    from agent_system.adapters.outbound.llm.agents import _get_model
    from agent_system.adapters.outbound.llm.journal_agent import run_journal_turn
    from agent_system.composition_root.config import get_settings

    settings = get_settings()
    return await run_journal_turn(message, deps=deps, model=_get_model(settings.default_model, api_key),
                                  history=history,
                                  max_requests=settings.chat_loop_max_requests,
                                  timeout_s=settings.chat_loop_timeout_s)


@router.post("/chat")
async def chat_about_day(payload: ChatRequest, current_user_id: CurrentUserId, session: SessionDep) -> StreamingResponse:
    """Talk with the journal agent about one day. Streams Server-Sent Events.

    A POST with the token in the Authorization header, so neither the message nor the
    token is ever in a URL. Events: tool_result, response_chunk, then response or error.
    """
    from agent_system.adapters.outbound.llm.journal_agent import JournalDeps, build_history
    from agent_system.adapters.outbound.telemetry import TurnTrace, bind_trace, install_llm_capture, set_current_node
    from agent_system.adapters.outbound.persistence.trace_repository import save_turn_trace
    from agent_system.composition_root.config import get_settings

    settings = get_settings()
    user = await _user(session, current_user_id)
    day = _valid_day(payload.date, _today(user.timezone))
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Say something first")
    api_key = _api_key(user, settings)
    if not api_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="No OpenAI API key available. Add one under Settings → API key.")
    repo = SQLAlchemyJournalRepository(session)
    timezone = user.timezone or "UTC"
    day_entries = [{"time": _local_time(e.created_at, timezone), "body": e.body}
                   for e in await repo.entries_for_day(current_user_id, day)]
    history = build_history([{"role": m.role, "content": m.content}
                             for m in await repo.messages_for_day(current_user_id, day, limit=12)])
    kg, embedder = await _memory_ports(api_key)

    queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()

    async def emit(event_type: str, node_name: str, text: str, data: dict | None = None) -> None:
        await queue.put(StreamEvent(event_type=event_type, node_name=node_name, message=text, data=data,
                                    timestamp=time.time()))

    async def reader(start: str | None, end: str | None, search: str | None, limit: int) -> list[dict[str, str]]:
        async with _own_session() as own:
            rows = await SQLAlchemyJournalRepository(own).find_entries(current_user_id, start=start, end=end,
                                                                      search=search, limit=limit)
        return [{"date": r.entry_date, "time": _local_time(r.created_at, timezone), "body": r.body} for r in rows]

    async def run() -> None:
        trace = TurnTrace()
        trace.user_input = message
        try:
            install_llm_capture()
            deps = JournalDeps(
                user_id=current_user_id, timezone=timezone, knowledge_graph_port=kg, embedding_port=embedder,
                trace=trace, emit=emit, session_factory=_own_session, day=day, day_entries=day_entries, reader=reader,
            )
            with bind_trace(trace):
                token = set_current_node("Journal")
                try:
                    trace.enter_node("Journal")
                    outcome = await run_turn(message, deps=deps, api_key=api_key, history=history)
                finally:
                    token.var.reset(token)
            answered = outcome.stopped == "answered"
            trace.finish(response=outcome.response, error=None if answered else outcome.stopped)

            # Save before announcing the reply: the browser hangs up on "response", and a
            # hang-up cancels this task.
            async with _own_session() as own:
                own_repo = SQLAlchemyJournalRepository(own)
                await own_repo.add_message(current_user_id, day, "user", message)
                saved = await own_repo.add_message(current_user_id, day, "assistant", outcome.response,
                                                   outcome.tools_used)
                await own.commit()
            await save_turn_trace(trace, user_id=current_user_id, conversation_id=f"journal:{day}", source="journal")
            await emit("response", "Journal", "Response complete", {
                "response": outcome.response, "message_id": saved.id, "tools_used": outcome.tools_used,
                "stopped": outcome.stopped,
            })
        except Exception as exc:  # noqa: BLE001
            logger.exception("journal chat failed")
            await emit("error", "Journal", f"Something went wrong ({type(exc).__name__}). Please try again.")
        finally:
            await queue.put(None)

    async def events() -> AsyncGenerator[str, None]:
        task = asyncio.create_task(run())
        try:
            while (event := await queue.get()) is not None:
                yield event.to_sse()
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
