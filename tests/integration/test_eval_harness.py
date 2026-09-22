"""End-to-end eval harness run against a real Neo4j (testcontainers) and SQLite,
with every LLM replaced by pydantic-ai's TestModel and a deterministic embedder.

Checks the plumbing, not model quality: seeding, the traced FSM run, scoring,
judging, persistence, and teardown.
"""

import hashlib
import math

import pytest

from agent_system.domain.ports.embedding import EmbeddingResult

pytestmark = pytest.mark.integration


class FakeEmbedder:
    """Bag-of-words hashing embedder: similar texts get similar vectors."""

    dims = 1536

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dims
        for w in text.lower().split():
            v[int(hashlib.md5(w.strip(".,!?").encode()).hexdigest(), 16) % self.dims] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    async def embed(self, text):
        return EmbeddingResult(text=text, embedding=self._vec(text), model="fake", dimensions=self.dims, tokens_used=len(text.split()))

    async def embed_batch(self, texts):
        return [await self.embed(t) for t in texts]

    def get_dimensions(self):
        return self.dims


@pytest.fixture(scope="module")
def neo4j_url():
    from testcontainers.neo4j import Neo4jContainer

    with Neo4jContainer("neo4j:5") as neo:
        yield neo.get_connection_url(), neo.username, neo.password


@pytest.fixture
async def harness_env(neo4j_url, tmp_path, monkeypatch):
    from pydantic_ai.models.test import TestModel

    from agent_system.adapters.outbound.llm import agents, knowledge_extractor
    from agent_system.composition_root import config, container
    from agent_system.evals import judges, runner

    uri, user, pw = neo4j_url
    monkeypatch.setenv("NEO4J_URI", uri)
    monkeypatch.setenv("NEO4J_USER", user)
    monkeypatch.setenv("NEO4J_PASSWORD", pw)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/evals.db")
    monkeypatch.setenv("EVAL_OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config.get_settings.cache_clear()
    monkeypatch.setattr(container, "_container", None)

    monkeypatch.setattr(agents, "_get_model", lambda *a, **k: TestModel())
    monkeypatch.setattr(knowledge_extractor, "_get_model_for_extraction", lambda *a, **k: TestModel())

    import agent_system.adapters.outbound.embedding as emb_pkg

    monkeypatch.setattr(emb_pkg, "OpenAIEmbeddingAdapter", lambda *a, **k: FakeEmbedder())
    monkeypatch.setattr(judges, "build_judges", lambda which, key: [judges._AgentJudge(TestModel())] if which != "none" else [])
    yield runner
    await container.shutdown_container()
    config.get_settings.cache_clear()


async def test_suite_run_persists_traced_results_and_cleans_up(harness_env):
    from sqlalchemy import select

    from agent_system.adapters.outbound.persistence import EvalCaseResultModel, EvalRunModel
    from agent_system.composition_root.container import get_container

    events = []

    async def progress(ev):
        events.append(ev)

    run_id = await harness_env.run_suite(
        "memory_retrieval", judge="openai", case_ids=["pet_treat", "semantic_past_discussion"],
        concurrency=2, progress=progress, analyze_failures=False,
    )

    c = await get_container()
    async with c.database.session() as s:
        run = await s.get(EvalRunModel, run_id)
        rows = (await s.execute(select(EvalCaseResultModel).where(EvalCaseResultModel.run_id == run_id))).scalars().all()

    assert run.status == "complete", run.error
    assert run.summary["cases"] == 2 and len(rows) == 2
    assert events[-1]["type"] == "run_done"
    for row in rows:
        assert row.error is None or "workflow error" not in row.error, row.error
        tr = row.turns[-1]["trace"]
        # full FSM ran and every visit is a timed span
        assert tr["path"][0] == "ReceiveInput" and tr["path"][-1] == "FinalizeKnowledge"
        assert all(sp["duration_ms"] is not None for sp in tr["spans"])
        # branch predicates were recorded
        assert any(d["node"] == "CheckPlan" for d in tr["decisions"])
        assert any(d["node"] == "AnalyzeIntent" for d in tr["decisions"])
        # LLM usage captured per node through the OTel processor
        assert tr["usage"]["llm_calls"] > 0 and tr["usage"]["input_tokens"] > 0
        # memory retrieval was recorded against the seeded graph
        assert any(r["source"] == "semantic_search" for r in tr["retrievals"])
        assert "judge" in str(row.judgements) or row.judgements
        assert "recall" in row.scores or "mentions" in row.scores

    # seeded past messages are real vector-searchable MessageEmbeddings, backdated
    from agent_system.evals.schema import load_suite
    from agent_system.evals.seed import seed_user, teardown_user

    case = next(c for c in load_suite("memory_retrieval").cases if c.id == "semantic_past_discussion")
    emb = FakeEmbedder()
    seeded = await seed_user(case, "t", c.database, c.knowledge_graph_adapter, emb)
    q = (await emb.embed(case.seed.messages[0].content)).embedding
    hits = await c.knowledge_graph_adapter.semantic_search(seeded.user.id, q, limit=5, min_score=0.9)
    assert hits and "cold brew" in hits[0]["content"]
    from datetime import datetime, timedelta

    assert hits[0]["created_at"] < (datetime.utcnow() - timedelta(days=9)).isoformat()  # backdated
    await teardown_user(seeded, c.database, c.knowledge_graph_adapter)

    # synthetic users are gone from both stores
    kg = c.knowledge_graph_adapter
    async with kg.driver.session(database=kg._database) as s:
        rec = await (await s.run("MATCH (n) WHERE n.user_id IS NOT NULL RETURN count(n) AS n")).single()
    assert rec["n"] == 0
