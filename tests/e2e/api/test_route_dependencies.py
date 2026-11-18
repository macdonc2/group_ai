"""Routes are handed the graph store, the calendar adapter and the research runner.

Each route names what it needs as a parameter, so a test replaces it with
`app.dependency_overrides` instead of patching a module attribute.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agent_system.adapters.inbound.api import create_app
from agent_system.adapters.inbound.api.auth import TokenData, get_current_user_token
from agent_system.adapters.inbound.api.dependencies import (
    get_app_container,
    get_google_calendar,
    get_knowledge_graph,
    get_session,
)
from agent_system.composition_root.config import Settings

USER_ID = "11111111-1111-1111-1111-111111111111"


class _Graph:
    def __init__(self) -> None:
        self.cleared: list[str] = []

    async def clear_user_graph(self, user_id: str) -> int:
        self.cleared.append(user_id)
        return 3


class _Calendar:
    def get_authorization_url(self, state: str) -> str:
        return f"https://accounts.example/auth?state={state}"


def _empty_container() -> SimpleNamespace:
    return SimpleNamespace(knowledge_graph_adapter=None, google_calendar_adapter=None)


@pytest.fixture
def app():
    app = create_app(Settings(openai_api_key=None, database_url="sqlite+aiosqlite:///:memory:", debug=False))
    app.dependency_overrides[get_session] = lambda: None  # these routes never touch the database
    return app


@pytest.fixture
def signed_in(app):
    app.dependency_overrides[get_current_user_token] = lambda: TokenData(user_id=USER_ID, email="a@example.com")
    return TestClient(app)  # no `with`: startup does not run, so nothing real is built


@pytest.mark.e2e
def test_a_route_uses_the_graph_store_it_is_given(app, signed_in):
    graph = _Graph()
    app.dependency_overrides[get_knowledge_graph] = lambda: graph
    r = signed_in.delete("/api/v1/knowledge/graph")
    assert r.status_code == 200
    assert r.json() == {"deleted_nodes": 3}
    assert graph.cleared == [USER_ID]


@pytest.mark.e2e
def test_a_route_uses_the_calendar_adapter_it_is_given(app, signed_in):
    app.dependency_overrides[get_google_calendar] = _Calendar
    r = signed_in.post("/api/v1/calendar/connect")
    assert r.status_code == 200
    assert r.json()["authorization_url"].startswith("https://accounts.example/auth?state=")


@pytest.mark.e2e
def test_missing_adapters_answer_503_with_the_same_messages_as_before(app, signed_in):
    app.dependency_overrides[get_app_container] = _empty_container
    r = signed_in.delete("/api/v1/knowledge/graph")
    assert (r.status_code, r.json()["detail"]) == (503, "Knowledge graph service not available")
    for method, path in [("post", "/api/v1/calendar/connect"), ("get", "/api/v1/calendar/events")]:
        r = getattr(signed_in, method)(path)
        assert (r.status_code, r.json()["detail"]) == (503, "Google Calendar integration is not configured")


@pytest.mark.e2e
def test_signing_in_is_still_checked_before_the_adapter(app):
    app.dependency_overrides[get_app_container] = _empty_container
    assert TestClient(app).delete("/api/v1/knowledge/graph").status_code == 401
    assert TestClient(app).post("/api/v1/calendar/connect").status_code == 401


@pytest.mark.e2e
def test_routes_get_the_container_the_app_built_at_startup(app, signed_in):
    graph = _Graph()
    app.state.container = SimpleNamespace(knowledge_graph_adapter=graph, google_calendar_adapter=None)
    assert signed_in.delete("/api/v1/knowledge/graph").json() == {"deleted_nodes": 3}


@pytest.mark.e2e
def test_a_websocket_route_is_handed_the_same_container():
    from fastapi import FastAPI, WebSocket

    from agent_system.adapters.inbound.api.dependencies import ContainerDep

    mini = FastAPI()
    mini.state.container = SimpleNamespace(knowledge_graph_adapter="the graph", google_calendar_adapter=None)

    @mini.websocket("/ws")
    async def ws(websocket: WebSocket, container: ContainerDep) -> None:
        await websocket.accept()
        await websocket.send_text(container.knowledge_graph_adapter)
        await websocket.close()

    with TestClient(mini).websocket_connect("/ws") as connection:
        assert connection.receive_text() == "the graph"
