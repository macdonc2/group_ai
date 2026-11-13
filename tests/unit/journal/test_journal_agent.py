"""The journal's side-chat agent: its tool set, what it is told, and its exits.

The real agent runs against a scripted `FunctionModel` with fake tool implementations,
so nothing here touches a model, a database or the network.
"""

from contextlib import asynccontextmanager

import pytest
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from agent_system.adapters.outbound.llm.journal_agent import (
    TOOL_NAMES,
    JournalDeps,
    build_history,
    journal_agent,
    run_journal_turn,
)
from agent_system.adapters.outbound.llm.tools import ToolResult

pytestmark = pytest.mark.unit


def scripted(*steps):
    """A model that plays `steps` in order: (tool, args) tuples, then a final string."""
    seen = {"results": [], "instructions": "", "tools": []}

    def run(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen["instructions"] = info.instructions or ""
        seen["tools"] = sorted(t.name for t in info.function_tools)
        returns = [p for m in messages if isinstance(m, ModelRequest) for p in m.parts if isinstance(p, ToolReturnPart)]
        seen["results"] = [str(p.content) for p in returns]
        step = steps[min(len(returns), len(steps) - 1)]
        if isinstance(step, tuple):
            return ModelResponse(parts=[ToolCallPart(step[0], step[1])])
        return ModelResponse(parts=[TextPart(step)])

    return FunctionModel(run), seen


def deps(**overrides) -> JournalDeps:
    calls: list[tuple[str, dict]] = []

    def make(name):
        async def call(**kwargs):
            calls.append((name, kwargs))
            return ToolResult(success=True, data=None, message=f"{name} ok")

        return call

    @asynccontextmanager
    async def session():
        yield object()

    async def reader(start, end, search, limit):
        calls.append(("reader", {"start": start, "end": end, "search": search}))
        return [{"date": "2026-11-10", "time": "08:00 AM", "body": "Sam got the promotion."}]

    built = JournalDeps(
        user_id="u1", timezone="America/Chicago", day="2026-11-13",
        day_entries=[{"time": "09:15 PM", "body": "Long day. Zane chewed the couch."}],
        impl={name: make(name) for name in ("recall_about_topic", "list_people", "list_pets", "list_places",
                                            "list_preferences", "get_upcoming_events", "add_to_calendar")},
        session_factory=session, reader=reader,
    )
    for name, value in overrides.items():
        setattr(built, name, value)
    built.calls = calls  # type: ignore[attr-defined]
    return built


async def test_the_journal_agent_has_no_web_tools():
    model, seen = scripted("ok")
    await run_journal_turn("hi", deps=deps(), model=model)
    assert seen["tools"] == sorted(TOOL_NAMES)
    assert not {"web_search", "read_webpage"} & set(seen["tools"])
    assert sorted(journal_agent._function_toolset.tools) == sorted(TOOL_NAMES)


async def test_it_is_told_the_open_day_and_what_was_written_on_it():
    model, seen = scripted("ok")
    await run_journal_turn("what do you make of today?", deps=deps(), model=model)
    assert "Open journal day: Friday, November 13, 2026 (2026-11-13)" in seen["instructions"]
    assert "Zane chewed the couch" in seen["instructions"]

    model, seen = scripted("ok")
    await run_journal_turn("hi", deps=deps(day_entries=[]), model=model)
    assert "Nothing has been written on the open day yet." in seen["instructions"]


async def test_read_journal_searches_through_the_callers_reader():
    d = deps()
    model, seen = scripted(("read_journal", {"search": "Sam"}), "Sam was promoted on the 10th.")
    outcome = await run_journal_turn("when did I mention Sam?", deps=d, model=model)

    assert outcome.stopped == "answered" and outcome.tools_used == ["read_journal"]
    assert d.calls == [("reader", {"start": None, "end": None, "search": "Sam"})]
    assert "Tuesday, November 10, 2026" in seen["results"][0] and "promotion" in seen["results"][0]


async def test_read_journal_takes_one_day_or_a_recent_window_and_rejects_nonsense():
    d = deps()
    model, _ = scripted(("read_journal", {"date": "2026-11-10"}), "done")
    await run_journal_turn("x", deps=d, model=model)
    assert d.calls[-1][1] == {"start": "2026-11-10", "end": "2026-11-10", "search": None}

    d = deps()
    model, _ = scripted(("read_journal", {"days_back": 7}), "done")
    await run_journal_turn("x", deps=d, model=model)
    assert d.calls[-1][1]["start"] < d.calls[-1][1]["end"]

    for bad in ({"date": "last tuesday"}, {}):
        d = deps()
        model, seen = scripted(("read_journal", bad), "done")
        await run_journal_turn("x", deps=d, model=model)
        assert d.calls == [] and seen["results"][0].startswith("Tool failed")


async def test_calendar_and_memory_tools_run_as_the_signed_in_user():
    d = deps()
    model, _ = scripted(("get_upcoming_events", {"timeframe": "today"}),
                        ("add_to_calendar", {"events": [{"title": "Vet", "when": "Friday 3pm"}]}),
                        ("recall_about_topic", {"topic": "Zane"}), "done")
    outcome = await run_journal_turn("add the vet on Friday at 3", deps=d, model=model)

    assert outcome.tools_used == ["get_upcoming_events", "add_to_calendar", "recall_about_topic"]
    assert [name for name, _ in d.calls] == ["get_upcoming_events", "add_to_calendar", "recall_about_topic"]
    assert all(kwargs["user_id"] == "u1" for _, kwargs in d.calls)
    assert d.calls[1][1]["events"] == [{"title": "Vet", "when": "Friday 3pm"}]


async def test_a_turn_that_never_answers_stops_at_the_request_cap():
    model, _ = scripted(("read_journal", {"search": "Sam"}))
    outcome = await run_journal_turn("x", deps=deps(), model=model, max_requests=3)
    assert outcome.stopped == "step_limit" and "stopped after 3 steps" in outcome.response


def test_history_keeps_roles_and_opens_with_the_user():
    history = build_history([{"role": "assistant", "content": "orphan"}, {"role": "user", "content": "hi"},
                             {"role": "assistant", "content": "hello"}])
    assert [type(m) for m in history] == [ModelRequest, ModelResponse]
