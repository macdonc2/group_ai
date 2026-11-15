"""Evals API (superusers only): suites, runs, case results, run comparison,
FSM topology and real-conversation traces for the predicate-tree viewer."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select

from agent_system.adapters.inbound.api.auth import RequireSuperuser
from agent_system.adapters.inbound.api.dependencies import SessionDep
from agent_system.adapters.outbound.persistence import (
    EvalCaseResultModel,
    EvalHumanLabelModel,
    EvalRunModel,
    TurnTraceModel,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/evals", tags=["evals"])

# Background eval tasks started from the API, by run id (in-process, like Deep Research).
_tasks: dict[str, asyncio.Task] = {}


class RunCreate(BaseModel):
    """Either a dataset `suite`, or `conversation_ids` (the caller's own real conversations)."""

    suite: str | None = None
    conversation_ids: list[str] | None = Field(default=None, max_length=50)
    rubrics: list[str] | None = None
    judge: str = Field(default="openai", pattern="^(openai|jev|both|none)$")
    repeats: int = Field(default=1, ge=1, le=5)
    concurrency: int = Field(default=2, ge=1, le=8)
    case_ids: list[str] | None = None


def _run_item(r: EvalRunModel, done: int | None = None) -> dict[str, Any]:
    s = r.summary or {}
    return {
        "id": r.id, "suite": r.suite, "status": r.status, "judge": r.judge, "git_sha": r.git_sha,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "pass_rate": s.get("pass_rate"), "cases": s.get("cases"), "passed": s.get("passed"),
        "pass_rate_interval": s.get("pass_rate_interval"),
        "cost_usd": (s.get("cost") or {}).get("system_usd"),
        "p50_ms": (s.get("latency") or {}).get("turn_p50_ms"),
        "total": (r.config or {}).get("total"), "done": done,
        "live": r.id in _tasks and not _tasks[r.id].done(),
    }


def _judge_means(judgements: dict[str, Any]) -> dict[str, float | None]:
    out = {}
    for jname, rubrics in (judgements or {}).items():
        if jname.startswith("_"):
            continue
        means = [r.get("mean") for r in rubrics.values() if isinstance(r, dict) and r.get("mean") is not None]
        out[jname] = round(sum(means) / len(means), 3) if means else None
    return out


@router.get("/suites")
async def list_suites(_: RequireSuperuser) -> list[dict[str, Any]]:
    from agent_system.evals.schema import list_suites as names
    from agent_system.evals.schema import load_suite

    out = []
    for name in names():
        s = load_suite(name)
        cases = s.research_cases if s.kind == "research" else s.cases
        out.append({"name": name, "kind": s.kind, "description": s.description, "rubrics": s.rubrics,
                    "cases": [c.id for c in cases]})
    return out


@router.get("/rubrics/{name}")
async def get_rubric(name: str, _: RequireSuperuser) -> dict[str, Any]:
    from agent_system.evals.judges import list_rubrics, load_rubric

    if name not in list_rubrics():
        raise HTTPException(status_code=404, detail="Unknown rubric")
    r = load_rubric(name)
    return {"name": r.name, "title": r.title, "dimensions": r.dimensions}


@router.get("/runs")
async def list_runs(_: RequireSuperuser, session: SessionDep, suite: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    stmt = select(EvalRunModel).order_by(desc(EvalRunModel.started_at)).limit(min(limit, 200))
    if suite:
        stmt = stmt.where(EvalRunModel.suite == suite)
    runs = list((await session.execute(stmt)).scalars())
    counts = dict((await session.execute(
        select(EvalCaseResultModel.run_id, func.count()).where(
            EvalCaseResultModel.run_id.in_([r.id for r in runs])
        ).group_by(EvalCaseResultModel.run_id)
    )).all()) if runs else {}
    return [_run_item(r, counts.get(r.id, 0)) for r in runs]


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
async def start_run(payload: RunCreate, token: RequireSuperuser) -> dict[str, Any]:
    from agent_system.adapters.inbound.api.dependencies import get_database
    from agent_system.evals.judges import list_rubrics
    from agent_system.evals.runner import run_conversations, run_suite
    from agent_system.evals.schema import list_suites as names

    if payload.conversation_ids:
        bad = [r for r in payload.rubrics or [] if r not in list_rubrics()]
        if bad:
            raise HTTPException(status_code=400, detail=f"Unknown rubrics: {bad}")
        suite_name, total = "conversations", len(payload.conversation_ids)
    elif payload.suite in names():
        suite_name, total = payload.suite, None
    else:
        raise HTTPException(status_code=404, detail=f"Unknown suite '{payload.suite}'")
    run_id = str(uuid.uuid4())

    # Create the row now so the tab can open the run the moment this returns.
    async with get_database().session() as s:
        s.add(EvalRunModel(id=run_id, suite=suite_name, judge=payload.judge, status="running",
                           config={"origin": "api", "total": total}))
        await s.commit()

    async def _go() -> None:
        try:
            if payload.conversation_ids:
                await run_conversations(payload.conversation_ids, token.user_id, judge=payload.judge,
                                        rubrics=payload.rubrics, run_id=run_id, origin="api")
            else:
                await run_suite(payload.suite, judge=payload.judge, repeats=payload.repeats,
                                concurrency=payload.concurrency, case_ids=payload.case_ids, run_id=run_id,
                                origin="api", preflight=True)
        except Exception as exc:  # noqa: BLE001 - surfaced on the run row
            logger.exception("eval run %s failed", run_id)
            async with get_database().session() as s:
                run = await s.get(EvalRunModel, run_id)
                if run is not None and run.status == "running":
                    run.status, run.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
                    await s.commit()
        finally:
            _tasks.pop(run_id, None)

    _tasks[run_id] = asyncio.create_task(_go(), name=f"eval-{run_id}")
    return {"id": run_id, "status": "running"}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, _: RequireSuperuser, session: SessionDep) -> dict[str, Any]:
    run = await session.get(EvalRunModel, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    done = (await session.execute(
        select(func.count()).where(EvalCaseResultModel.run_id == run_id)
    )).scalar_one()
    return {**_run_item(run, done), "config": run.config, "summary": run.summary,
            "failure_analysis_md": run.failure_analysis_md, "error": run.error}


@router.get("/runs/{run_id}/cases")
async def list_case_results(run_id: str, _: RequireSuperuser, session: SessionDep) -> list[dict[str, Any]]:
    rows = (await session.execute(
        select(EvalCaseResultModel).where(EvalCaseResultModel.run_id == run_id)
        .order_by(EvalCaseResultModel.case_id, EvalCaseResultModel.repeat)
    )).scalars()
    return [{
        "id": r.id, "case_id": r.case_id, "repeat": r.repeat, "passed": r.passed, "failure_tags": r.failure_tags,
        "description": (r.case or {}).get("description") or "",
        "user": (r.turns[-1]["user"] if r.turns else (r.case or {}).get("question")),
        "scores": {k: {"score": v["score"], "passed": v["passed"]} for k, v in (r.scores or {}).items()},
        "judge_means": _judge_means(r.judgements),
        "total_ms": r.total_ms, "cost_usd": r.cost_usd, "error": r.error,
    } for r in rows]


@router.get("/cases/{result_id}")
async def get_case_result(result_id: str, _: RequireSuperuser, session: SessionDep) -> dict[str, Any]:
    r = await session.get(EvalCaseResultModel, result_id)
    if not r:
        raise HTTPException(status_code=404, detail="Case result not found")
    judgements = {k: v for k, v in (r.judgements or {}).items() if not k.startswith("_")}
    return {
        "id": r.id, "run_id": r.run_id, "case_id": r.case_id, "repeat": r.repeat, "passed": r.passed,
        "failure_tags": r.failure_tags, "case": r.case, "scores": r.scores, "judgements": judgements,
        "entity_snapshot": (r.judgements or {}).get("_snapshot"), "turns": r.turns,
        "total_ms": r.total_ms, "cost_usd": r.cost_usd, "judge_cost_usd": r.judge_cost_usd, "error": r.error,
        "labels": await _labels(session, [r.id]),
    }


async def _labels(session: Any, result_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Human labels for one result as {rubric: {passed, note}}."""
    rows = (await session.execute(
        select(EvalHumanLabelModel).where(EvalHumanLabelModel.result_id.in_(result_ids))
    )).scalars()
    return {row.rubric: {"passed": row.passed, "note": row.note} for row in rows}


class LabelIn(BaseModel):
    """`passed: null` removes the label."""

    passed: bool | None
    note: str = Field(default="", max_length=2000)


@router.put("/cases/{result_id}/labels/{rubric}")
async def set_label(result_id: str, rubric: str, payload: LabelIn, token: RequireSuperuser,
                    session: SessionDep) -> dict[str, Any]:
    """Record a person's pass/fail on a case result: per rubric, or "overall" for the whole case."""
    from agent_system.evals.calibration import OVERALL
    from agent_system.evals.judges import list_rubrics

    if rubric != OVERALL and rubric not in list_rubrics():
        raise HTTPException(status_code=400, detail=f"Unknown rubric '{rubric}'")
    if not await session.get(EvalCaseResultModel, result_id):
        raise HTTPException(status_code=404, detail="Case result not found")
    row = (await session.execute(
        select(EvalHumanLabelModel).where(EvalHumanLabelModel.result_id == result_id,
                                          EvalHumanLabelModel.rubric == rubric)
    )).scalar_one_or_none()
    if payload.passed is None:
        if row is not None:
            await session.delete(row)
    elif row is None:
        session.add(EvalHumanLabelModel(id=str(uuid.uuid4()), result_id=result_id, rubric=rubric,
                                        passed=payload.passed, note=payload.note, user_id=token.user_id))
    else:
        row.passed, row.note, row.user_id = payload.passed, payload.note, token.user_id
    await session.commit()
    return {"labels": await _labels(session, [result_id])}


@router.get("/calibration")
async def calibration(_: RequireSuperuser, session: SessionDep, suite: str | None = None) -> dict[str, Any]:
    """How often each grader agrees with the human labels, across every labelled case result."""
    from agent_system.evals.calibration import MIN_LABELS, MIN_PER_CLASS, calibrate, rows_for_result
    from agent_system.evals.schema import list_suites as names
    from agent_system.evals.schema import load_suite

    query = (select(EvalHumanLabelModel, EvalCaseResultModel, EvalRunModel.suite)
             .join(EvalCaseResultModel, EvalCaseResultModel.id == EvalHumanLabelModel.result_id)
             .join(EvalRunModel, EvalRunModel.id == EvalCaseResultModel.run_id))
    if suite:
        query = query.where(EvalRunModel.suite == suite)
    by_result: dict[str, dict[str, Any]] = {}
    for label, result, suite_name in (await session.execute(query)).all():
        entry = by_result.setdefault(result.id, {
            "result": {"id": result.id, "run_id": result.run_id, "case_id": result.case_id,
                       "passed": result.passed, "judgements": result.judgements},
            "suite": suite_name, "labels": {}})
        entry["labels"][label.rubric] = {"passed": label.passed, "note": label.note}
    thresholds = {n: load_suite(n).pass_threshold for n in names()}
    rows = [row for e in by_result.values()
            for row in rows_for_result(e["result"], e["labels"], thresholds.get(e["suite"], 3.5))]
    return {"labelled_results": len(by_result), "labels": sum(len(e["labels"]) for e in by_result.values()),
            "min_labels": MIN_LABELS, "min_per_class": MIN_PER_CLASS, "graders": calibrate(rows)}


@router.get("/compare")
async def compare_runs(a: str, b: str, _: RequireSuperuser, session: SessionDep) -> dict[str, Any]:
    ra, rb = await session.get(EvalRunModel, a), await session.get(EvalRunModel, b)
    if not ra or not rb:
        raise HTTPException(status_code=404, detail="Run not found")

    def flat(summary: dict[str, Any]) -> dict[str, float | None]:
        out: dict[str, float | None] = {"pass_rate": summary.get("pass_rate")}
        out.update({f"det.{k}": v for k, v in (summary.get("deterministic") or {}).items()})
        for j, dims in (summary.get("judge") or {}).items():
            out.update({f"{j}.{k}": v for k, v in dims.items()})
        lat, cost = summary.get("latency") or {}, summary.get("cost") or {}
        out.update({"latency.p50_ms": lat.get("turn_p50_ms"), "latency.p95_ms": lat.get("turn_p95_ms"),
                    "cost.per_case_usd": cost.get("per_case_usd")})
        return out

    fa, fb = flat(ra.summary or {}), flat(rb.summary or {})
    rows = []
    for key in sorted(set(fa) | set(fb)):
        va, vb = fa.get(key), fb.get(key)
        rows.append({"metric": key, "a": va, "b": vb,
                     "delta": round(vb - va, 4) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else None})

    from agent_system.evals import stats

    async def attempts(run_id: str) -> dict[str, list[bool]]:
        res = (await session.execute(select(EvalCaseResultModel.case_id, EvalCaseResultModel.passed)
                                     .where(EvalCaseResultModel.run_id == run_id))).all()
        return stats.group_by_case({"case_id": cid, "passed": ok} for cid, ok in res)

    pa, pb = await attempts(a), await attempts(b)
    oa, ob = {k: all(v) for k, v in pa.items()}, {k: all(v) for k, v in pb.items()}
    return {
        "a": _run_item(ra), "b": _run_item(rb), "metrics": rows,
        # the two runs share their cases, so the test is paired: see evals/stats.py
        "paired": stats.paired_comparison(pa, pb),
        "regressions": sorted(k for k in oa if oa[k] and ob.get(k) is False),
        "fixes": sorted(k for k in oa if not oa[k] and ob.get(k) is True),
    }


@router.get("/graph")
async def fsm_graph(_: RequireSuperuser) -> dict[str, Any]:
    from agent_system.adapters.outbound.fsm.workflow import workflow_topology

    return workflow_topology()


@router.get("/conversations")
async def traced_conversations(token: RequireSuperuser, session: SessionDep, limit: int = Query(100, le=300)) -> list[dict[str, Any]]:
    """The caller's own recent conversations, with how many turns carry a trace."""
    from agent_system.evals.conversations import list_user_conversations

    return await list_user_conversations(session, token.user_id, limit=limit)


@router.get("/traces/conversation/{conversation_id}")
async def conversation_traces(conversation_id: str, token: RequireSuperuser, session: SessionDep) -> list[dict[str, Any]]:
    """Turns of one of the caller's conversations; `trace` is null for turns from before tracing."""
    from agent_system.evals.conversations import load_conversation

    loaded = await load_conversation(session, conversation_id, token.user_id)
    if loaded is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return [{"user": t["user"], "response": t["response"], "trace": t["trace"], "created_at": t["at"]}
            for t in loaded[1]]


@router.get("/traces/{trace_id}")
async def get_trace(trace_id: str, token: RequireSuperuser, session: SessionDep) -> dict[str, Any]:
    t = await session.get(TurnTraceModel, trace_id)
    if not t or t.user_id != token.user_id:
        raise HTTPException(status_code=404, detail="Trace not found")
    return {"id": t.id, "conversation_id": t.conversation_id, "trace": t.trace}
