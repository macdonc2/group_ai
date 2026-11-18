"""Tools are handed what they need by whoever runs them; they do not fetch it.

The state machine used to open a database session by calling the global container, and the
calendar tools fetched the calendar adapter the same way. Both now come from the turn's
dependencies, and which arguments a tool is given is read from its signature.
"""

from contextlib import asynccontextmanager

import pytest
from pydantic_graph import GraphRunContext

from agent_system.adapters.outbound.fsm import nodes
from agent_system.adapters.outbound.fsm.state import AgentDependencies, WorkflowState
from agent_system.adapters.outbound.llm import tools
from agent_system.adapters.outbound.llm.chat_agent import ChatDeps, _session
from agent_system.domain.entities import Conversation, User

pytestmark = pytest.mark.unit

CALENDAR = object()


class _Sessions:
    def __init__(self) -> None:
        self.opened = 0
        self.closed = 0

    def factory(self):
        @asynccontextmanager
        async def _open():
            self.opened += 1
            try:
                yield "the session"
            finally:
                self.closed += 1

        return _open()


def _ctx(**deps) -> GraphRunContext:
    user = User.create(email="tools@example.com", hashed_password="x")
    state = WorkflowState(user=user, conversation=Conversation.create(user_id=user.id))
    return GraphRunContext(state=state, deps=AgentDependencies(
        llm_port=None, user_repository=None, conversation_repository=None, plan_repository=None,
        knowledge_graph_port=None, **deps))


def test_tool_accepts_reads_the_signature_not_the_function_body():
    async def declares(user_id: str) -> None: ...

    async def only_a_local(query: str) -> None:
        user_id = query  # a local with the same name is not a parameter
        del user_id

    async def takes_anything(**kwargs) -> None: ...

    assert tools.tool_accepts(declares, "user_id")
    assert not tools.tool_accepts(only_a_local, "user_id")
    assert "user_id" in only_a_local.__code__.co_varnames  # what the old check looked at
    assert tools.tool_accepts(takes_anything, "user_id")


async def test_an_event_tool_gets_a_session_the_user_and_the_calendar_from_the_turn(monkeypatch):
    seen: dict = {}

    async def fake_events(user_id: str, **kwargs):
        seen.update(user_id=user_id, **kwargs)
        return tools.ToolResult(success=True, data=None, message="2 events")

    monkeypatch.setitem(tools.AVAILABLE_TOOLS["get_upcoming_events"], "function", fake_events)
    sessions = _Sessions()
    ctx = _ctx(session_factory=sessions.factory, google_calendar=CALENDAR)
    ctx.state.tool_name, ctx.state.tool_arguments = "get_upcoming_events", {"timeframe": "week"}

    await nodes.ExecuteTool().run(ctx)

    assert seen == {"user_id": str(ctx.state.user.id), "timeframe": "week", "session": "the session",
                    "google_calendar": CALENDAR}
    assert (sessions.opened, sessions.closed) == (1, 1)  # opened for this call and closed after it
    assert ctx.state.tool_result == "2 events"


async def test_an_event_tool_without_a_session_factory_fails_without_being_called(monkeypatch):
    async def fake_events(user_id: str, **kwargs):
        raise AssertionError("must not run without a session")

    monkeypatch.setitem(tools.AVAILABLE_TOOLS["get_upcoming_events"], "function", fake_events)
    ctx = _ctx()
    ctx.state.tool_name, ctx.state.tool_arguments = "get_upcoming_events", {}

    await nodes.ExecuteTool().run(ctx)

    assert "database" in ctx.state.tool_result


async def test_a_tool_that_needs_no_session_does_not_open_one(monkeypatch):
    async def fake_calc(expression: str):
        return tools.ToolResult(success=True, data=None, message="4")

    monkeypatch.setitem(tools.AVAILABLE_TOOLS["calculate"], "function", fake_calc)
    sessions = _Sessions()
    ctx = _ctx(session_factory=sessions.factory)
    ctx.state.tool_name, ctx.state.tool_arguments = "calculate", {"expression": "2+2"}

    await nodes.ExecuteTool().run(ctx)

    assert sessions.opened == 0


async def test_the_loop_engine_gives_event_tools_no_session_when_it_has_no_factory():
    async with _session(ChatDeps(user_id="u-1")) as session:
        assert session is None
    sessions = _Sessions()
    async with _session(ChatDeps(user_id="u-1", session_factory=sessions.factory)) as session:
        assert session == "the session"
    assert (sessions.opened, sessions.closed) == (1, 1)


async def test_the_state_machine_runs_a_replacement_tool_and_the_interceptor_from_the_turn(monkeypatch):
    async def real_search(query: str, num_results: int = 5):
        raise AssertionError("the real tool must not run when the turn replaces it")

    async def stand_in(query: str, num_results: int = 5):
        return tools.ToolResult(success=True, data=[], message=f"stand-in saw {query}")

    seen: list[str] = []

    async def interceptor(name, kwargs):
        seen.append(name)
        return None  # let the call through

    monkeypatch.setitem(tools.AVAILABLE_TOOLS["web_search"], "function", real_search)
    ctx = _ctx(tool_overrides={"web_search": stand_in}, tool_interceptor=interceptor)
    ctx.state.tool_name, ctx.state.tool_arguments = "web_search", {"query": "jazz"}

    await nodes.ExecuteTool().run(ctx)

    assert seen == ["web_search"]
    assert ctx.deps.trace is None  # no trace needed for this path
    assert tools.AVAILABLE_TOOLS["web_search"]["function"] is real_search  # the registry was not touched


async def test_an_interceptor_can_fail_a_state_machine_tool_call():
    async def interceptor(name, kwargs):
        return tools.ToolResult(success=False, data=None, message="429 rate limited")

    ctx = _ctx(tool_interceptor=interceptor)
    ctx.state.tool_name, ctx.state.tool_arguments = "calculate", {"expression": "2+2"}

    await nodes.ExecuteTool().run(ctx)

    assert ctx.state.tool_result == "Tool failed: 429 rate limited"


def test_the_loop_engine_merges_replacements_over_its_own_tools():
    from agent_system.adapters.outbound.llm.chat_agent import tool_implementations

    async def stand_in(**kwargs): ...

    merged = tool_implementations({"web_search": stand_in})
    assert merged["web_search"] is stand_in
    assert merged["calculate"] is tools.calculate
    assert tool_implementations()["web_search"] is tools.web_search


async def test_the_loop_engine_runs_the_interceptor_from_its_dependencies():
    from types import SimpleNamespace

    from agent_system.adapters.outbound.llm.chat_agent import _call, tool_implementations

    async def calculate(expression: str):
        return tools.ToolResult(success=True, data=None, message="4")

    async def interceptor(name, kwargs):
        return tools.ToolResult(success=False, data=None, message=f"{name} is down") if name == "calculate" else None

    impl = tool_implementations({"calculate": calculate})
    plain = SimpleNamespace(deps=ChatDeps(user_id="u-1", impl=impl))
    faulty = SimpleNamespace(deps=ChatDeps(user_id="u-1", impl=impl, interceptor=interceptor))

    assert (await _call(plain, "calculate", expression="2+2")).message == "4"
    assert (await _call(faulty, "calculate", expression="2+2")).message == "calculate is down"
