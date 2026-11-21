"""The calendar sync service is handed its encryption; it does not look up the secret key."""

from types import SimpleNamespace

import pytest

from agent_system.application.services import CalendarSyncService
from agent_system.domain.utils.encryption import APIKeyEncryption

pytestmark = pytest.mark.unit


class _Calendar:
    def __init__(self) -> None:
        self.refreshed_with: list[str] = []

    async def refresh_access_token(self, refresh_token: str):
        self.refreshed_with.append(refresh_token)
        return SimpleNamespace(access_token="access-1")


def _user(encrypted: str):
    return SimpleNamespace(email="u@example.com", encrypted_google_refresh_token=encrypted,
                           has_google_calendar_connected=lambda: True)


async def test_it_decrypts_the_stored_token_with_the_encryption_it_was_given():
    encryption = APIKeyEncryption("s" * 48)
    calendar = _Calendar()
    service = CalendarSyncService(calendar, encryption)

    token = await service._get_access_token(_user(encryption.encrypt("refresh-abc")))

    assert token == "access-1"
    assert calendar.refreshed_with == ["refresh-abc"]


async def test_a_token_stored_under_another_key_is_not_readable():
    calendar = _Calendar()
    service = CalendarSyncService(calendar, APIKeyEncryption("s" * 48))

    token = await service._get_access_token(_user(APIKeyEncryption("o" * 48).encrypt("refresh-abc")))

    assert token is None
    assert calendar.refreshed_with == []


def test_the_factory_builds_it_from_the_secret_key(monkeypatch):
    from agent_system.composition_root.config import get_api_key_encryption, get_settings

    monkeypatch.setenv("SECRET_KEY", "k" * 48)
    get_settings.cache_clear()
    try:
        assert APIKeyEncryption("k" * 48).decrypt(get_api_key_encryption().encrypt("x")) == "x"
    finally:
        get_settings.cache_clear()
