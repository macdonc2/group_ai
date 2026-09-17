"""The runner with every model call and network call faked.

Checks the event order, per-lane failure isolation, persistence for replay,
live fan-out with seq dedupe, and the interrupted-on-startup marking.
"""

import asyncio

import pytest
import pytest_asyncio

from agent_system.adapters.outbound.persistence import Database
from agent_system.adapters.outbound.persistence.research_repositories import SQLAlchemyResearchRepository
from agent_system.adapters.outbound.persistence.models import UserModel
from agent_system.adapters.outbound.research import runner as runner_mod
from agent_system.adapters.outbound.research.runner import ResearchRunner, ResearchSettings, mark_interrupted_on_startup
from agent_system.adapters.outbound.research.schemas import SectionPlan, Synthesis
from agent_system.domain.entities.research import (
    DataPoint, DataSeries, DataTable, Finding, LaneResult, ResearchStatus, Source,
)

USER = "11111111-1111-1111-1111-111111111111"


@pytest_asyncio.fixture
async def db():
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_tables()
    async with database.session() as s:
        s.add(UserModel(id=USER, email="u@example.com", hashed_password="x"))
        await s.commit()
    yield database
    await database.dispose()


def _fake_pipeline(monkeypatch, *, practical_fails=False, narration_fails=False):
    seen: dict = {}
    async def fake_lanes(question, deps, emit):
        results = {}
        for lane in ("academic", "practical", "empirical"):
            await emit("lane_start", lane, "start", None)
            if lane == "practical" and practical_fails:
                await emit("lane_error", lane, "boom", {"error": "boom"})
                results[lane] = LaneResult(lane=lane, error="boom")
                continue
            src = Source(id=f"{lane[0].upper()}1", lane=lane, title=f"{lane} source", snippet="s")
            await emit("lane_sources", lane, "1 source", {"sources": [src.model_dump(exclude={'snippet'})]})
            await emit("lane_finding", lane, "claim", {"source_id": src.id, "confidence": 0.9})
            tables = []
            if lane == "empirical":
                tables = [DataTable(title="Speed", series=[DataSeries(name="m", points=[DataPoint(x="a", y=1), DataPoint(x="b", y=2)])], source_ids=[src.id])]
                await emit("lane_tables", lane, "1 table", {"tables": [t.model_dump() for t in tables]})
            await emit("lane_complete", lane, "done", {"findings": 1, "sources": 1, "tables": len(tables)})
            results[lane] = LaneResult(lane=lane, sources=[src], findings=[Finding(claim="claim", evidence="e", source_id=src.id)], tables=tables)
        return results

    async def fake_extra(question, academic, deps):
        return []

    async def fake_synth(question, results, tables, refs, model, key):
        return Synthesis(title="The Title", tldr="Short.", sections=[SectionPlan(heading="Background and Motivation", key_points=["p"])],
                         figures_to_use=[1])

    async def fake_write(*args, **kwargs):
        for piece in ["# The Title\n\n", "**TL;DR** Short.\n\n## What the Numbers Show\n\n", "![Figure 1](figure:1)\n\nDone [1]."]:
            yield piece

    async def fake_speech(text, api_key, model, voice, persona=None):
        if narration_fails:
            raise RuntimeError("tts down")
        seen["speech_persona"] = persona
        return b"ID3fake-mp3"

    async def fake_write_capturing(*args, **kwargs):
        seen["write_persona"] = kwargs.get("persona")
        async for piece in fake_write():
            yield piece

    async def no_source_figs(sources, findings, max_total=2):
        return []

    monkeypatch.setattr(runner_mod.source_figures, "figures_from_sources", no_source_figs)
    monkeypatch.setattr(runner_mod, "run_all_lanes", fake_lanes)
    monkeypatch.setattr(runner_mod, "empirical_from_academic", fake_extra)
    monkeypatch.setattr(runner_mod.writer, "synthesize", fake_synth)
    monkeypatch.setattr(runner_mod.writer, "write_report", fake_write_capturing)
    monkeypatch.setattr(runner_mod.narration, "synthesize_speech", fake_speech)
    return seen


def _settings():
    return ResearchSettings(strong_model="openai:strong", fast_model="openai:fast", tts_model="tts", tts_voice="marin")


async def _create(db, question="How do X and Y compare?"):
    async with db.session() as s:
        job = await SQLAlchemyResearchRepository(s).create(USER, question, "openai:strong")
        await s.commit()
    return job


@pytest.mark.unit
async def test_happy_path_persists_everything(db, monkeypatch):
    _fake_pipeline(monkeypatch)
    r = ResearchRunner(db, _settings())
    job = await _create(db)
    q = asyncio.Queue()
    r.start(job.id, "sk-test")
    live = r.subscribe(job.id)
    assert live is not None
    await r._jobs[job.id].task

    async with db.session() as s:
        repo = SQLAlchemyResearchRepository(s)
        done = await repo.get(job.id)
        events = await repo.get_events(job.id)
        figures = await repo.list_figures(job.id)
        audio = await repo.get_audio(job.id)

    assert done.status == ResearchStatus.COMPLETE
    assert done.title == "The Title" and done.tldr == "Short."
    assert "## References" in done.report_markdown and "(figure:1)" in done.report_markdown
    assert [s.ref for s in done.sources] == [1, 2, 3]
    assert done.progress.phase == "complete" and done.progress.figures == 1 and done.progress.has_audio
    assert all(done.progress.lanes[l].status == "complete" for l in ("academic", "practical", "empirical"))
    assert len(figures) == 1 and figures[0].caption.startswith("Figure 1: Speed")
    assert audio == (b"ID3fake-mp3", "marin")

    types = [e["event_type"] for e in events]
    assert types[0] == "job_start" and types[-1] == "job_complete"
    for name in ("lane_complete", "synthesis_complete", "figure_rendered", "report_complete", "narration_complete"):
        assert name in types
    assert "writing_chunk" not in types  # not persisted
    seqs = [e["data"]["seq"] for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

    # live subscribers saw the chunks and the terminal None
    seen = []
    while not live.empty():
        seen.append(live.get_nowait())
    assert seen[-1] is None
    assert any(e and e["event_type"] == "writing_chunk" for e in seen)


@pytest.mark.unit
async def test_one_lane_failing_still_completes(db, monkeypatch):
    _fake_pipeline(monkeypatch, practical_fails=True)
    r = ResearchRunner(db, _settings())
    job = await _create(db)
    r.start(job.id, "sk-test")
    await r._jobs[job.id].task
    async with db.session() as s:
        done = await SQLAlchemyResearchRepository(s).get(job.id)
    assert done.status == ResearchStatus.COMPLETE
    assert done.progress.lanes["practical"].status == "error"
    assert done.progress.lanes["practical"].error == "boom"


@pytest.mark.unit
async def test_narration_failure_is_not_fatal(db, monkeypatch):
    _fake_pipeline(monkeypatch, narration_fails=True)
    r = ResearchRunner(db, _settings())
    job = await _create(db)
    r.start(job.id, "sk-test")
    await r._jobs[job.id].task
    async with db.session() as s:
        repo = SQLAlchemyResearchRepository(s)
        done = await repo.get(job.id)
        types = [e["event_type"] for e in await repo.get_events(job.id)]
    assert done.status == ResearchStatus.COMPLETE and not done.progress.has_audio
    assert "narration_failed" in types and types[-1] == "job_complete"


@pytest.mark.unit
async def test_pipeline_exception_marks_failed(db, monkeypatch):
    async def explode(question, deps, emit):
        raise RuntimeError("no network")
    monkeypatch.setattr(runner_mod, "run_all_lanes", explode)
    r = ResearchRunner(db, _settings())
    job = await _create(db)
    r.start(job.id, "sk-test")
    await r._jobs[job.id].task
    async with db.session() as s:
        done = await SQLAlchemyResearchRepository(s).get(job.id)
    assert done.status == ResearchStatus.FAILED and "no network" in done.error
    assert not r.is_live(job.id) and r.subscribe(job.id) is None


@pytest.mark.unit
async def test_interrupted_on_startup(db):
    job = await _create(db)
    async with db.session() as s:
        await SQLAlchemyResearchRepository(s).update_fields(job.id, status=ResearchStatus.WRITING)
        await s.commit()
    assert await mark_interrupted_on_startup(db) == 1
    async with db.session() as s:
        done = await SQLAlchemyResearchRepository(s).get(job.id)
    assert done.status == ResearchStatus.INTERRUPTED and "restarted" in done.error
    assert await mark_interrupted_on_startup(db) == 0


@pytest.mark.unit
async def test_persona_reaches_writer_and_narration(db, monkeypatch):
    seen = _fake_pipeline(monkeypatch)
    r = ResearchRunner(db, _settings())
    job = await _create(db)
    async with db.session() as s:
        repo = SQLAlchemyResearchRepository(s)
        p = job.progress
        p.persona = "mean_gene"
        await repo.update_fields(job.id, progress=p)
        await s.commit()
    r.start(job.id, "sk-test")
    await r._jobs[job.id].task
    assert seen["write_persona"] == "mean_gene" and seen["speech_persona"] == "mean_gene"
    async with db.session() as s:
        done = await SQLAlchemyResearchRepository(s).get(job.id)
    assert done.progress.persona == "mean_gene" and done.status == ResearchStatus.COMPLETE
