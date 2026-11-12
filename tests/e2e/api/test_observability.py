"""Request IDs, the access log, JSON log lines and the readiness check."""

import json
import logging

import pytest
from starlette.testclient import TestClient

from agent_system.adapters.inbound.api import create_app
from agent_system.adapters.inbound.api.observability import JsonFormatter, RequestContextFilter
from agent_system.composition_root.config import Settings, get_settings

API = "/api/v1"
PASSWORD = "correct-horse-battery"


class _Capture(logging.Handler):
    """Collects records as the JSON the production formatter would emit."""

    def __init__(self) -> None:
        super().__init__()
        self.addFilter(RequestContextFilter())
        self.setFormatter(JsonFormatter())
        self.lines: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(json.loads(self.format(record)))

    def access(self) -> list[dict]:
        return [line for line in self.lines if line.get("event") == "http_request"]


@pytest.fixture
def app_and_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k" * 48)
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    get_settings.cache_clear()
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'obs.db'}", debug=False)
    app = create_app(settings)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    capture = _Capture()
    with TestClient(app, raise_server_exceptions=False) as client:
        logging.getLogger().addHandler(capture)  # after create_app, which resets handlers
        try:
            yield client, capture
        finally:
            logging.getLogger().removeHandler(capture)
    get_settings.cache_clear()


@pytest.mark.e2e
def test_every_response_carries_a_request_id(app_and_logs):
    client, _ = app_and_logs
    first = client.get("/").headers["x-request-id"]
    second = client.get("/").headers["x-request-id"]
    assert len(first) == 32 and first != second


@pytest.mark.e2e
def test_a_sane_incoming_request_id_is_kept_and_a_hostile_one_is_replaced(app_and_logs):
    client, _ = app_and_logs
    kept = client.get("/", headers={"X-Request-ID": "upstream-trace-0001"})
    assert kept.headers["x-request-id"] == "upstream-trace-0001"

    # Log injection attempt: newlines and JSON in a header that ends up in every log line.
    hostile = 'x"}\n{"level":"INFO","msg":"forged"'
    replaced = client.get("/", headers={"X-Request-ID": hostile})
    assert replaced.headers["x-request-id"] != hostile and len(replaced.headers["x-request-id"]) == 32


@pytest.mark.e2e
def test_access_log_names_the_route_user_and_request_but_not_ids_or_tokens(app_and_logs):
    client, logs = app_and_logs
    token = client.post(f"{API}/auth/bootstrap", json={"email": "a@example.com", "password": PASSWORD}).json()
    conversation = client.post(
        f"{API}/conversations", json={"title": "t"}, headers={"Authorization": f"Bearer {token['access_token']}"},
    ).json()
    logs.lines.clear()

    r = client.get(
        f"{API}/conversations/{conversation['id']}?token=should-never-be-logged",
        headers={"Authorization": f"Bearer {token['access_token']}"},
    )
    (entry,) = logs.access()
    assert entry["path"] == f"{API}/conversations/{{conversation_id}}"  # the template, not the ID
    assert entry["method"] == "GET" and entry["status"] == 200
    assert entry["request_id"] == r.headers["x-request-id"]
    assert entry["user_id"] == token["user"]["id"]
    assert entry["duration_ms"] >= 0
    assert "should-never-be-logged" not in json.dumps(logs.lines)


@pytest.mark.e2e
def test_log_lines_written_during_a_request_share_its_id(app_and_logs):
    client, logs = app_and_logs
    r = client.post(f"{API}/auth/login", json={"email": "nobody@example.com", "password": "wrong-password"})
    assert r.status_code == 401
    request_id = r.headers["x-request-id"]

    during = [line for line in logs.lines if line.get("request_id") == request_id]
    assert {line["logger"] for line in during} >= {
        "agent_system.adapters.inbound.api.routes.auth",  # "Failed login ..."
        "agent_system.access",
    }
    (access,) = [line for line in during if line.get("event") == "http_request"]
    assert access["level"] == "WARNING" and access["status"] == 401  # refusals stand out
    assert "nobody@example.com" not in json.dumps(logs.lines)  # no emails in logs


@pytest.mark.e2e
def test_an_unhandled_error_is_logged_with_its_traceback_and_returns_the_id(app_and_logs):
    client, logs = app_and_logs
    r = client.get("/boom")
    assert r.status_code == 500
    assert r.json() == {"detail": "Internal server error", "request_id": r.headers["x-request-id"]}

    (error,) = [line for line in logs.lines if line.get("event") == "unhandled_error"]
    assert error["request_id"] == r.headers["x-request-id"]
    assert "RuntimeError: kaboom" in error["exc"]
    (access,) = logs.access()
    assert access["status"] == 500 and access["level"] == "ERROR"


@pytest.mark.e2e
def test_successful_health_probes_are_not_logged(app_and_logs):
    client, logs = app_and_logs
    assert client.get("/health").status_code == 200
    assert client.get("/health/ready").status_code == 200
    assert logs.access() == []


@pytest.mark.e2e
def test_readiness_reports_each_dependency(app_and_logs):
    client, _ = app_and_logs
    body = client.get("/health/ready").json()
    assert body["status"] == "ready" and body["checks"]["database"] == "ok"
    assert body["checks"]["graph"] in ("ok", "down", "not_connected")


@pytest.mark.e2e
def test_readiness_fails_when_the_database_is_down_but_liveness_does_not(app_and_logs, monkeypatch):
    client, logs = app_and_logs

    def broken():
        raise RuntimeError("database unreachable")

    monkeypatch.setattr("agent_system.adapters.inbound.api.main.get_database", broken)
    r = client.get("/health/ready")
    assert r.status_code == 503
    assert r.json()["status"] == "not_ready" and r.json()["checks"]["database"] == "down"
    assert client.get("/health").status_code == 200  # a restart wouldn't help, so don't ask for one
    assert any(line.get("event") == "dependency_down" and line["dependency"] == "database" for line in logs.lines)
    assert [line["status"] for line in logs.access()] == [503]  # a failing probe *is* logged


@pytest.mark.unit
def test_telemetry_export_is_off_without_an_endpoint():
    from agent_system.adapters.outbound.telemetry import otel

    assert otel.setup_telemetry(object(), endpoint=None, environment="development") is False
    assert otel.telemetry_enabled() is False
    # Every helper is a safe no-op, so call sites never need to check.
    assert otel.current_trace_ids() is None
    otel.record_turn("chat", "ok")
    otel.annotate_current_span(**{"app.request_id": "x"})
    otel.instrument_database(object())
    otel.shutdown_telemetry()
