"""CORS, response headers and API docs exposure."""

import pytest
from starlette.testclient import TestClient

from agent_system.adapters.inbound.api import create_app
from agent_system.composition_root.config import Settings, get_settings

API = "/api/v1"


def _client(tmp_path, monkeypatch, *, deployed: bool, **overrides):
    monkeypatch.setenv("SECRET_KEY", "k" * 48)
    if deployed:
        monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    else:
        monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    get_settings.cache_clear()
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'p.db'}", debug=False, **overrides)
    return TestClient(create_app(settings))


@pytest.fixture(autouse=True)
def _reset_settings():
    yield
    get_settings.cache_clear()


def _preflight(client, origin: str):
    return client.options(
        f"{API}/conversations",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"},
    )


@pytest.mark.e2e
def test_deployed_app_grants_no_other_website_access(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deployed=True) as client:
        for origin in ("https://evil.example", "https://agent.macdonml.com.evil.example", "null"):
            simple = client.get(f"{API}/auth/me", headers={"Origin": origin})
            assert "access-control-allow-origin" not in simple.headers
            assert "access-control-allow-credentials" not in simple.headers
            assert "access-control-allow-origin" not in _preflight(client, origin).headers


@pytest.mark.e2e
def test_only_listed_origins_are_allowed_and_never_with_credentials(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deployed=True, cors_allow_origins="https://app.example, https://other.example") as client:
        ok = _preflight(client, "https://app.example")
        assert ok.headers["access-control-allow-origin"] == "https://app.example"
        assert "access-control-allow-credentials" not in ok.headers
        assert "access-control-allow-origin" not in _preflight(client, "https://evil.example").headers


@pytest.mark.e2e
def test_local_development_allows_the_vite_dev_server(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deployed=False) as client:
        assert _preflight(client, "http://localhost:5173").headers["access-control-allow-origin"] == "http://localhost:5173"
        assert "access-control-allow-origin" not in _preflight(client, "https://evil.example").headers


@pytest.mark.e2e
def test_api_responses_tell_the_browser_not_to_render_frame_or_cache_them(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deployed=True) as client:
        for response in (client.get(f"{API}/auth/me"), client.post(f"{API}/auth/login", json={})):  # a 401 and a 422
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["x-frame-options"] == "DENY"
            assert response.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
            assert response.headers["referrer-policy"] == "no-referrer"
            assert response.headers["cache-control"] == "no-store"


@pytest.mark.e2e
def test_api_docs_are_off_when_deployed_and_on_locally(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deployed=True) as client:
        assert [client.get(p).status_code for p in ("/docs", "/redoc", "/openapi.json")] == [404, 404, 404]
    with _client(tmp_path, monkeypatch, deployed=False) as client:
        assert [client.get(p).status_code for p in ("/docs", "/openapi.json")] == [200, 200]
    with _client(tmp_path, monkeypatch, deployed=True, enable_api_docs=True) as client:
        assert client.get("/openapi.json").status_code == 200
