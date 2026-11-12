"""Tokens follow the account, logins are throttled, weak signing keys are refused.

No model or network call happens.
"""

import sqlite3

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agent_system.adapters.inbound.api import create_app
from agent_system.adapters.inbound.api.auth import TokenData, create_access_token
from agent_system.adapters.inbound.api.routes import auth as auth_routes
from agent_system.adapters.inbound.api.throttle import FailureThrottle
from agent_system.composition_root.config import Settings, get_settings, secret_key_problem

API = "/api/v1"
PASSWORD = "correct-horse-battery"
STRONG_KEY = "k" * 48


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", STRONG_KEY)
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    get_settings.cache_clear()
    auth_routes.account_throttle.reset()
    auth_routes.address_throttle.reset()
    yield
    get_settings.cache_clear()


@pytest.fixture
def world(tmp_path):
    """An admin (Alice) and an ordinary verified user (Bob), each with a token."""
    db_path = tmp_path / "auth.db"
    settings = Settings(database_url=f"sqlite+aiosqlite:///{db_path}", debug=False)
    with TestClient(create_app(settings)) as client:
        boot = client.post(f"{API}/auth/bootstrap", json={"email": "alice@example.com", "password": PASSWORD}).json()
        alice = boot["access_token"]
        bob_user = client.post(
            f"{API}/auth/register", json={"email": "bob@example.com", "password": PASSWORD}, headers=_bearer(alice),
        ).json()
        bob = client.post(f"{API}/auth/login", json={"email": "bob@example.com", "password": PASSWORD}).json()["access_token"]
        yield {
            "client": client, "alice": alice, "alice_id": boot["user"]["id"],
            "bob": bob, "bob_id": bob_user["id"], "db_path": db_path,
        }


# -- tokens follow the account ---------------------------------------------


@pytest.mark.e2e
def test_deactivated_user_is_locked_out_at_once(world):
    client = world["client"]
    assert client.get(f"{API}/auth/me", headers=_bearer(world["bob"])).status_code == 200

    done = client.post(f"{API}/auth/users/{world['bob_id']}/deactivate", headers=_bearer(world["alice"]))
    assert done.status_code == 200, done.text

    # Same token, still unexpired and correctly signed.
    assert client.get(f"{API}/auth/me", headers=_bearer(world["bob"])).status_code == 401
    assert client.get(f"{API}/conversations", headers=_bearer(world["bob"])).status_code == 401
    # The paths that take the token another way are covered too.
    assert client.get(f"{API}/research/any/stream", params={"token": world["bob"]}).status_code == 401
    assert client.get(f"{API}/agent/chat/stream", params={"message": "hi", "token": world["bob"]}).status_code == 401
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(f"{API}/groups/g/conversations/c/ws", subprotocols=["bearer", world["bob"]]):
            pass
    assert closed.value.code == 4401


@pytest.mark.e2e
def test_deleted_user_token_stops_working(world):
    client = world["client"]
    assert client.delete(f"{API}/auth/users/{world['bob_id']}", headers=_bearer(world["alice"])).status_code == 204
    assert client.get(f"{API}/auth/me", headers=_bearer(world["bob"])).status_code == 401


@pytest.mark.e2e
def test_admin_rights_come_from_the_database_not_the_token(world):
    client = world["client"]
    assert client.get(f"{API}/auth/users", headers=_bearer(world["alice"])).status_code == 200

    # Alice loses admin rights while still holding a token that says is_superuser.
    with sqlite3.connect(world["db_path"]) as db:
        db.execute("UPDATE users SET is_superuser = 0 WHERE id = ?", (world["alice_id"],))
    assert client.get(f"{API}/auth/users", headers=_bearer(world["alice"])).status_code == 403
    assert client.get(f"{API}/auth/me", headers=_bearer(world["alice"])).status_code == 200  # still a user


@pytest.mark.e2e
def test_a_token_claiming_admin_does_not_make_one(world):
    forged_claims = create_access_token(TokenData(user_id=world["bob_id"], email="bob@example.com", is_superuser=True))
    assert world["client"].get(f"{API}/auth/users", headers=_bearer(forged_claims)).status_code == 403


# -- login throttling ------------------------------------------------------


def _login(client, email: str, password: str, address: str = "203.0.113.7"):
    return client.post(f"{API}/auth/login", json={"email": email, "password": password}, headers={"X-Real-IP": address})


@pytest.mark.e2e
def test_repeated_failures_are_throttled_even_with_the_right_password(world):
    client = world["client"]
    for _ in range(5):
        assert _login(client, "bob@example.com", "wrong-password").status_code == 401

    blocked = _login(client, "bob@example.com", PASSWORD)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


@pytest.mark.e2e
def test_the_real_owner_elsewhere_is_not_locked_out(world):
    client = world["client"]
    for _ in range(5):
        _login(client, "bob@example.com", "wrong-password", address="203.0.113.7")
    assert _login(client, "bob@example.com", PASSWORD, address="198.51.100.20").status_code == 200


@pytest.mark.e2e
def test_one_address_trying_many_emails_is_throttled(world):
    client = world["client"]
    for i in range(30):
        assert _login(client, f"guess{i}@example.com", "wrong-password").status_code == 401
    assert _login(client, "another@example.com", "wrong-password").status_code == 429


@pytest.mark.e2e
def test_unknown_email_and_wrong_password_look_the_same(world):
    client = world["client"]
    unknown = _login(client, "nobody@example.com", "wrong-password")
    wrong = _login(client, "bob@example.com", "wrong-password")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


@pytest.mark.unit
def test_throttle_window_slides():
    now = [0.0]
    throttle = FailureThrottle(limit=2, window_s=60, clock=lambda: now[0])
    throttle.fail("k")
    now[0] = 30
    throttle.fail("k")
    assert throttle.retry_after("k") == 31  # until the first failure ages out
    assert throttle.retry_after("other") == 0
    now[0] = 61
    assert throttle.retry_after("k") == 0
    throttle.fail("k")
    assert throttle.retry_after("k") > 0
    throttle.clear("k")
    assert throttle.retry_after("k") == 0


# -- signing key -----------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("key", "ok"),
    [
        ("change-me-in-production", False),
        ("your-secret-key-for-jwt-min-32-chars", False),  # .env.example placeholder: long enough, still public
        ("short", False),
        (STRONG_KEY, True),
    ],
)
def test_secret_key_problem(key, ok):
    assert (secret_key_problem(key) is None) is ok


@pytest.mark.e2e
@pytest.mark.parametrize("deployed_by", ["app_env", "kubernetes"])
def test_refuses_to_start_deployed_with_a_placeholder_key(tmp_path, monkeypatch, deployed_by):
    monkeypatch.setenv("SECRET_KEY", "change-me-in-production")
    get_settings.cache_clear()
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'x.db'}")
    if deployed_by == "app_env":
        settings = settings.model_copy(update={"app_env": "production"})
    else:
        monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")

    with pytest.raises(RuntimeError, match="Refusing to start"):
        with TestClient(create_app(settings)):
            pass


@pytest.mark.e2e
def test_placeholder_key_only_warns_in_development(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "change-me-in-production")
    get_settings.cache_clear()
    with TestClient(create_app(Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'x.db'}"))) as client:
        assert client.get("/health").status_code == 200
