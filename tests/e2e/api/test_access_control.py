"""One signed-in user must not reach another user's data.

Two users, Alice (owner of everything created here) and Mallory (a valid
account with no relationship to Alice). Every test asks the same question:
can Mallory, or someone with no token at all, touch what is Alice's?

No model or network call happens.
"""

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agent_system.adapters.inbound.api import create_app
from agent_system.composition_root.config import Settings

API = "/api/v1"
PASSWORD = "correct-horse-battery"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A running app with Alice's conversation, plan and group in it."""
    # The chat route reads the cached global settings; give it a key so the
    # test reaches the ownership check whatever the machine's .env holds.
    from agent_system.composition_root.config import get_settings

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    get_settings.cache_clear()
    settings = Settings(
        openai_api_key="sk-test", database_url=f"sqlite+aiosqlite:///{tmp_path / 'acl.db'}", debug=False,
    )
    with TestClient(create_app(settings)) as client:
        boot = client.post(f"{API}/auth/bootstrap", json={"email": "alice@example.com", "password": PASSWORD})
        assert boot.status_code == 200, boot.text
        alice = boot.json()["access_token"]
        made = client.post(
            f"{API}/auth/register", json={"email": "mallory@example.com", "password": PASSWORD}, headers=_bearer(alice),
        )
        assert made.status_code == 201, made.text
        mallory = client.post(
            f"{API}/auth/login", json={"email": "mallory@example.com", "password": PASSWORD},
        ).json()["access_token"]

        conversation = client.post(f"{API}/conversations", json={"title": "Private"}, headers=_bearer(alice)).json()
        plan = client.post(
            f"{API}/plans",
            json={"goal_description": "Secret plan", "success_criteria": ["done"], "steps": [{"description": "step"}]},
            headers=_bearer(alice),
        )
        assert plan.status_code == 201, plan.text
        group = client.post(f"{API}/groups", json={"name": "Family"}, headers=_bearer(alice)).json()
        group_conversation = client.post(
            f"{API}/groups/{group['id']}/conversations", json={"title": "Chat"}, headers=_bearer(alice),
        ).json()

        yield {
            "client": client, "alice": alice, "mallory": mallory,
            "alice_id": boot.json()["user"]["id"],
            "conversation_id": conversation["id"], "plan_id": plan.json()["id"],
            "ws_path": f"{API}/groups/{group['id']}/conversations/{group_conversation['id']}/ws",
        }
    get_settings.cache_clear()


# -- conversations ---------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("get", "", None),
        ("patch", "", {"title": "Hijacked"}),
        ("post", "/archive", None),
        ("delete", "", None),
    ],
)
def test_another_users_conversation_looks_missing(world, method, suffix, body):
    url = f"{API}/conversations/{world['conversation_id']}{suffix}"
    r = world["client"].request(method, url, json=body, headers=_bearer(world["mallory"]))
    assert r.status_code == 404  # not 403: the ID's existence is not confirmed either

    # ...and nothing happened to it.
    mine = world["client"].get(f"{API}/conversations/{world['conversation_id']}", headers=_bearer(world["alice"]))
    assert mine.status_code == 200 and mine.json()["title"] == "Private"


@pytest.mark.e2e
def test_cannot_chat_into_another_users_conversation(world):
    r = world["client"].post(
        f"{API}/agent/chat",
        json={"message": "what did we talk about?", "conversation_id": world["conversation_id"]},
        headers=_bearer(world["mallory"]),
    )
    assert r.status_code == 404


# -- plans -----------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("method", "suffix"),
    [("get", ""), ("post", "/activate"), ("post", "/pause"), ("post", "/cancel"), ("delete", "")],
)
def test_another_users_plan_looks_missing(world, method, suffix):
    url = f"{API}/plans/{world['plan_id']}{suffix}"
    assert world["client"].request(method, url, headers=_bearer(world["mallory"])).status_code == 404
    assert world["client"].get(f"{API}/plans/{world['plan_id']}", headers=_bearer(world["alice"])).status_code == 200


# -- tool endpoints --------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.parametrize(
    "path", ["/tools", "/tools/search?query=x", "/tools/datetime", "/tools/calculate?expression=1%2B1",
             "/tools/fact", "/tools/define/word"],
)
def test_tool_endpoints_need_a_login(world, path):
    assert world["client"].get(f"{API}{path}").status_code == 401


@pytest.mark.e2e
def test_tool_endpoints_work_when_signed_in(world):
    r = world["client"].get(f"{API}/tools/calculate?expression=2%2B3", headers=_bearer(world["mallory"]))
    assert r.status_code == 200 and r.json()["success"] is True


# -- group chat socket -----------------------------------------------------


def _refused(client: TestClient, path: str, subprotocols: list[str] | None = None) -> int:
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(path, subprotocols=subprotocols):
            pass
    return closed.value.code


@pytest.mark.e2e
def test_socket_refuses_a_claimed_user_id_without_a_token(world):
    # The old contract: say who you are in the URL. It must no longer work.
    assert _refused(world["client"], f"{world['ws_path']}?user_id={world['alice_id']}") == 4401


@pytest.mark.e2e
def test_socket_refuses_a_bad_token(world):
    assert _refused(world["client"], world["ws_path"], ["bearer", "not-a-token"]) == 4401


@pytest.mark.e2e
def test_socket_refuses_a_valid_user_who_is_not_a_member(world):
    # Claiming Alice's id in the URL changes nothing: identity comes from the token.
    path = f"{world['ws_path']}?user_id={world['alice_id']}"
    assert _refused(world["client"], path, ["bearer", world["mallory"]]) == 4003


@pytest.mark.e2e
def test_socket_accepts_a_member_with_a_token(world):
    with world["client"].websocket_connect(world["ws_path"], subprotocols=["bearer", world["alice"]]) as ws:
        assert ws.accepted_subprotocol == "bearer"
