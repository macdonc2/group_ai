"""A conversation remembers the wrestler it was last spoken in.

PATCH sets/clears it, list and detail expose it, unknown keys are rejected.
No model or network call happens.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from agent_system.adapters.inbound.api import create_app
from agent_system.adapters.inbound.api.auth import TokenData, create_access_token
from agent_system.composition_root.config import Settings

USER_ID = "55555555-5555-5555-5555-555555555555"


@pytest.fixture
async def client():
    from agent_system.adapters.inbound.api.dependencies import set_database
    from agent_system.adapters.outbound.persistence import Database
    from agent_system.adapters.outbound.persistence.models import UserModel

    app = create_app(Settings(openai_api_key="sk-test", database_url="sqlite+aiosqlite:///:memory:", debug=False))
    db = Database("sqlite+aiosqlite:///:memory:", echo=False)
    await db.create_tables()
    set_database(db)
    async with db.session() as s:
        s.add(UserModel(id=USER_ID, email="p@example.com", hashed_password="x"))
        await s.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await db.dispose()


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(TokenData(user_id=USER_ID, email='p@example.com'))}"}


@pytest.mark.e2e
async def test_persona_is_stored_listed_cleared_and_validated(client: AsyncClient):
    created = (await client.post("/api/v1/conversations", json={"title": "Themed"}, headers=_auth())).json()
    assert created["persona"] is None
    cid = created["id"]

    r = await client.patch(f"/api/v1/conversations/{cid}", json={"persona": "macho_man"}, headers=_auth())
    assert r.status_code == 200 and r.json()["persona"] == "macho_man"

    listed = {c["id"]: c for c in (await client.get("/api/v1/conversations", headers=_auth())).json()}
    assert listed[cid]["persona"] == "macho_man"
    assert (await client.get(f"/api/v1/conversations/{cid}", headers=_auth())).json()["persona"] == "macho_man"

    # title-only PATCH leaves the persona alone
    r = await client.patch(f"/api/v1/conversations/{cid}", json={"title": "Renamed"}, headers=_auth())
    assert r.json()["persona"] == "macho_man" and r.json()["title"] == "Renamed"

    assert (await client.patch(f"/api/v1/conversations/{cid}", json={"persona": "andre_the_giant"}, headers=_auth())).status_code == 422

    r = await client.patch(f"/api/v1/conversations/{cid}", json={"persona": "none"}, headers=_auth())
    assert r.status_code == 200 and r.json()["persona"] is None
