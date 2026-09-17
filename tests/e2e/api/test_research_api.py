"""Deep Research API: create → list → get → stream → figure/audio 404s → delete.

The runner is replaced with a fake that emits a short scripted event stream,
so no model or network call happens.
"""

import asyncio
import json
import time

import pytest
from httpx import ASGITransport, AsyncClient

from agent_system.adapters.inbound.api import create_app
from agent_system.adapters.inbound.api.auth import TokenData, create_access_token
from agent_system.adapters.outbound.persistence.research_repositories import SQLAlchemyResearchRepository
from agent_system.adapters.outbound.research import runner as runner_mod
from agent_system.composition_root.config import Settings

USER_ID = "44444444-4444-4444-4444-444444444444"


class FakeRunner:
    """Emits three events (persisted like the real one), then completes."""

    def __init__(self, db):
        self._db = db
        self.started: list[str] = []
        self._subs: dict[str, list[asyncio.Queue]] = {}
        self._done: set[str] = set()

    def start(self, job_id: str, api_key: str) -> None:
        self.started.append(job_id)
        asyncio.get_event_loop().create_task(self._run(job_id))

    async def _run(self, job_id: str) -> None:
        events = [
            ("job_start", None, "Research started"),
            ("lane_complete", "academic", "Academic lane done"),
            ("job_complete", None, "Done"),
        ]
        for seq, (t, node, msg) in enumerate(events, 1):
            await asyncio.sleep(0.05)
            ev = {"event_type": t, "node_name": node, "message": msg, "data": {"seq": seq}, "timestamp": time.time()}
            async with self._db.session() as s:
                repo = SQLAlchemyResearchRepository(s)
                await repo.append_event(job_id, ev)
                if t == "job_complete":
                    await repo.update_fields(job_id, status="complete", report_markdown="# Done\n\nbody", title="Done")
                await s.commit()
            for q in self._subs.get(job_id, []):
                q.put_nowait(ev)
        self._done.add(job_id)
        for q in self._subs.get(job_id, []):
            q.put_nowait(None)

    def subscribe(self, job_id: str):
        if job_id in self._done:
            return None
        q: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(job_id, []).append(q)
        return q

    def unsubscribe(self, job_id: str, q) -> None:
        self._subs.get(job_id, []).remove(q)

    def is_live(self, job_id: str) -> bool:
        return job_id not in self._done

    async def cancel(self, job_id: str) -> bool:
        return False


@pytest.fixture
def settings() -> Settings:
    return Settings(openai_api_key="sk-test", database_url="sqlite+aiosqlite:///:memory:", debug=False)


@pytest.fixture
async def client(settings, monkeypatch):
    from agent_system.adapters.inbound.api.dependencies import set_database
    from agent_system.adapters.outbound.persistence import Database
    from agent_system.adapters.outbound.persistence.models import UserModel

    app = create_app(settings)
    db = Database("sqlite+aiosqlite:///:memory:", echo=False)
    await db.create_tables()
    set_database(db)
    async with db.session() as s:
        s.add(UserModel(id=USER_ID, email="r@example.com", hashed_password="x"))
        await s.commit()

    fake = FakeRunner(db)
    runner_mod.set_runner(fake)  # type: ignore[arg-type]
    monkeypatch.setattr("agent_system.adapters.inbound.api.routes.research.get_runner", lambda: fake)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.fake = fake  # type: ignore[attr-defined]
        yield c
    await db.dispose()


def _auth(user_id: str = USER_ID) -> dict[str, str]:
    token = create_access_token(TokenData(user_id=user_id, email="r@example.com"))
    return {"Authorization": f"Bearer {token}"}


def _token(user_id: str = USER_ID) -> str:
    return create_access_token(TokenData(user_id=user_id, email="r@example.com"))


@pytest.mark.e2e
async def test_full_lifecycle(client: AsyncClient):
    # create
    r = await client.post("/api/v1/research", json={"question": "Does X beat Y on Z?", "depth": 2, "persona": "Hulk_Hogan"}, headers=_auth())
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] == "queued" and job["question"] == "Does X beat Y on Z?" and job["depth"] == 2
    assert job["persona"] == "hulk_hogan"
    bad = await client.post("/api/v1/research", json={"question": "another long question", "persona": "ultimate_warrior"}, headers=_auth())
    assert bad.status_code == 202 and bad.json()["persona"] is None
    assert client.fake.started[0] == job["id"]  # type: ignore[attr-defined]

    # stream: replay + live until terminal
    r = await client.get(f"/api/v1/research/{job['id']}/stream", params={"token": _token()})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    types = [json.loads(line[6:])["event_type"] for line in r.text.splitlines() if line.startswith("data: ")]
    assert types == ["job_start", "lane_complete", "job_complete"]

    # list + get
    r = await client.get("/api/v1/research", headers=_auth())
    assert job["id"] in [j["id"] for j in r.json()]
    assert next(j for j in r.json() if j["id"] == job["id"])["status"] == "complete"
    r = await client.get(f"/api/v1/research/{job['id']}", headers=_auth())
    d = r.json()
    assert d["title"] == "Done" and d["report_markdown"].startswith("# Done")
    assert d["depth"] == 2 and d["progress"]["depth"] == 2
    assert (await client.post("/api/v1/research", json={"question": "long enough question", "depth": 4}, headers=_auth())).status_code == 422
    assert d["figure_list"] == [] and d["has_audio"] is False

    # a second stream after completion replays and closes cleanly
    r = await client.get(f"/api/v1/research/{job['id']}/stream", params={"token": _token(), "after": 1})
    types = [json.loads(line[6:])["event_type"] for line in r.text.splitlines() if line.startswith("data: ")]
    assert types == ["lane_complete", "job_complete"]

    # figure / audio not present
    assert (await client.get(f"/api/v1/research/{job['id']}/figures/1", params={"token": _token()})).status_code == 404
    assert (await client.get(f"/api/v1/research/{job['id']}/audio", headers=_auth())).status_code == 404

    # delete
    assert (await client.delete(f"/api/v1/research/{job['id']}", headers=_auth())).status_code == 204
    assert (await client.get(f"/api/v1/research/{job['id']}", headers=_auth())).status_code == 404


@pytest.mark.e2e
async def test_other_users_cannot_see_or_stream(client: AsyncClient):
    r = await client.post("/api/v1/research", json={"question": "Private question here"}, headers=_auth())
    job_id = r.json()["id"]
    other = "55555555-5555-5555-5555-555555555555"
    assert (await client.get(f"/api/v1/research/{job_id}", headers=_auth(other))).status_code == 404
    assert (await client.get(f"/api/v1/research/{job_id}/stream", params={"token": _token(other)})).status_code == 404
    assert (await client.get("/api/v1/research", headers=_auth(other))).json() == []


@pytest.mark.e2e
async def test_validation_and_auth(client: AsyncClient):
    assert (await client.post("/api/v1/research", json={"question": "short"}, headers=_auth())).status_code == 422
    assert (await client.post("/api/v1/research", json={"question": "long enough question"})).status_code in (401, 403)
    assert (await client.get("/api/v1/research/nope/stream")).status_code == 401
