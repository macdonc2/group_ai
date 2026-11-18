"""The API builds its long-lived objects once, at startup, and everything shares them.

Before this, the app's lifespan built one `Database` and the first call to `get_container()`
built a second one, so the process held two connection pools, and readiness could not see the
graph store until some request had happened to create the container.
"""

import pytest
from fastapi.testclient import TestClient

from agent_system.adapters.inbound.api import create_app
from agent_system.adapters.inbound.api.dependencies import get_database
from agent_system.composition_root import container as container_module
from agent_system.composition_root.config import Settings, get_settings


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k" * 48)
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    get_settings.cache_clear()
    # No system model key, so startup makes no graph or model calls.
    yield Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'one.db'}", debug=False, openai_api_key=None)
    get_settings.cache_clear()


class _Driver:
    def __init__(self) -> None:
        self.checked = 0
        self.closed = False

    async def verify_connectivity(self) -> None:
        self.checked += 1

    async def close(self) -> None:
        self.closed = True


class _Graph:
    def __init__(self) -> None:
        self._driver = _Driver()


@pytest.mark.e2e
async def test_startup_registers_one_container_and_shutdown_clears_it(settings, monkeypatch):
    monkeypatch.setattr(container_module, "_container", None)
    app = create_app(settings)
    with TestClient(app) as client:
        built = app.state.container
        assert built is not None
        assert built.settings is settings                       # the settings given to create_app, not the global ones
        assert client.portal.call(container_module.get_container) is built  # no second container
        assert get_database() is built.database                 # one database, so one connection pool
    assert container_module._container is None
    assert app.state.container is None


@pytest.mark.e2e
def test_readiness_sees_the_graph_store_before_any_other_request(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        graph = _Graph()
        app.state.container.knowledge_graph_adapter = graph
        body = client.get("/health/ready").json()               # the very first request
        assert body["checks"]["graph"] == "ok"
        assert graph._driver.checked == 1
        app.state.container.knowledge_graph_adapter = None
        assert client.get("/health/ready").json()["checks"]["graph"] == "not_connected"


@pytest.mark.e2e
async def test_container_setup_gives_up_on_a_graph_store_that_does_not_answer(monkeypatch, tmp_path):
    """Index setup now runs during startup, so it is bounded: the app starts without waiting."""
    import asyncio

    class _SlowGraph:
        def __init__(self, **_: object) -> None:
            pass

        async def connect(self) -> None:
            pass

        async def ensure_vector_index(self, dimensions: int = 0) -> bool:
            await asyncio.sleep(30)
            return True

        async def ensure_temporal_index(self) -> bool:
            return True

    monkeypatch.setattr(container_module, "Neo4jAdapter", _SlowGraph)
    monkeypatch.setattr(container_module, "GRAPH_SETUP_TIMEOUT_S", 0.05)
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'slow.db'}", openai_api_key="sk-test")
    built = await asyncio.wait_for(container_module.Container.create(settings), 5)
    try:
        assert built.knowledge_graph_adapter is not None        # kept: it may answer later
        assert built.embedding_adapter is not None
    finally:
        await built.database.dispose()
