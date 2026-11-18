"""An app uses the settings it was created with, not whatever the process-wide ones are.

Before this, `create_app(settings)` took settings but login tokens were signed and
checked with the global `get_settings()`, so an app built with its own secret key
quietly ignored it.
"""

import pytest
from fastapi.testclient import TestClient

from agent_system.adapters.inbound.api import create_app
from agent_system.adapters.inbound.api.auth import TokenData, create_access_token, decode_access_token
from agent_system.composition_root.config import Settings, get_settings

API = "/api/v1"
PASSWORD = "correct horse battery staple 42"
APP_KEY = "a" * 48
GLOBAL_KEY = "g" * 48


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", GLOBAL_KEY)
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    get_settings.cache_clear()
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'own.db'}", debug=False,
                        openai_api_key=None, secret_key=APP_KEY)
    with TestClient(create_app(settings)) as client:
        yield client
    get_settings.cache_clear()


def _me(client: TestClient, token: str) -> int:
    return client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code


@pytest.mark.e2e
def test_login_tokens_are_signed_and_checked_with_the_apps_own_key(client):
    boot = client.post(f"{API}/auth/bootstrap", json={"email": "alice@example.com", "password": PASSWORD})
    assert boot.status_code == 200, boot.text
    token = boot.json()["access_token"]

    claims = decode_access_token(token, APP_KEY)
    assert claims is not None                              # signed with the app's key...
    assert decode_access_token(token, GLOBAL_KEY) is None  # ...not the process-wide one
    assert _me(client, token) == 200

    same_claims_global_key = create_access_token(TokenData(user_id=claims.user_id, email=claims.email))
    assert decode_access_token(same_claims_global_key, GLOBAL_KEY) is not None
    assert _me(client, same_claims_global_key) == 401      # a token this app did not sign


@pytest.mark.e2e
def test_token_helpers_fall_back_to_the_process_wide_key(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", GLOBAL_KEY)
    get_settings.cache_clear()
    try:
        token = create_access_token(TokenData(user_id="u", email="u@example.com"))
        assert decode_access_token(token) is not None
        assert decode_access_token(token, GLOBAL_KEY) is not None
        assert decode_access_token(token, APP_KEY) is None
    finally:
        get_settings.cache_clear()
