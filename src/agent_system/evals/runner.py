"""Run an eval suite end to end and persist the results.

For each case (× repeats): seed a synthetic user → play the turns through the
real FSM (`run_agent_workflow`) with a TurnTrace attached → deterministic
scores → rubric judges → tear the user down → store an EvalCaseResult. Then
aggregate the run (pass rate, per-dimension means, judge agreement, latency
percentiles, cost) and write the failure analysis.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from agent_system.adapters.outbound.telemetry import TurnTrace, bind_trace, install_llm_capture
from agent_system.evals import judges as judges_mod
from agent_system.evals.schema import EvalCase, ResearchCase, Suite, load_suite
from agent_system.evals.scorers import percentile, score_agent_case, score_research_sources
from agent_system.evals.seed import seed_user, snapshot_entities, teardown_user

logger = logging.getLogger(__name__)

ProgressCb = Callable[[dict[str, Any]], Awaitable[None]]

DEFAULT_CRITERIA = "Answer the user's final message correctly, using what is known about them where relevant."


# ---------------------------------------------------------------------------
# Context formatting for judges
# ---------------------------------------------------------------------------


def fmt_seed(case: EvalCase) -> str:
    s = case.seed
    lines = []
    for p in s.people:
        lines.append(f"- person {p.name} ({p.relationship_type or 'known'})"
                     + (f", aka {', '.join(p.aliases)}" if p.aliases else "")
                     + (f": {p.context_notes}" if p.context_notes else ""))
    for p in s.pets:
        lines.append(f"- pet {p.name}: {p.species or 'pet'}{' / ' + p.breed if p.breed else ''}"
                     + (f"; personality {', '.join(p.personality)}" if p.personality else "")
                     + (f"; likes {', '.join(p.food_preferences)}" if p.food_preferences else ""))
    for loc in s.locations:
        lines.append(f"- place {loc.name} ({loc.location_type or 'place'}, {loc.neighborhood or ''} {loc.city or ''})".strip())
    for pref in s.preferences:
        lines.append(f"- preference {pref.category}: {pref.value} ({'likes' if pref.sentiment > 0 else 'dislikes'})")
    for m in s.messages:
        lines.append(f"- {m.days_ago}d ago the {m.role} said: \"{m.content}\"")
    return "\n".join(lines) or "(nothing stored — the assistant should not claim to remember anything)"


def fmt_transcript(turns: list[dict[str, Any]]) -> str:
    return "\n\n".join(f"User: {t['user']}\nAssistant: {t['response']}" for t in turns)


def fmt_retrieved(trace: dict[str, Any]) -> str:
    out = []
    for r in trace.get("retrievals", []):
        out.append(f"[{r['source']}] query={r['query']!r}")
        for i, h in enumerate(r.get("hits", [])[:10], 1):
            score = f" score={h['score']:.2f}" if isinstance(h.get("score"), (int, float)) else ""
            used = "" if h.get("used_in_prompt", True) else " (not in prompt)"
            text = h.get("content") or h.get("name") or ""
            out.append(f"  {i}.{score}{used} {str(text)[:300]}")
    for t in trace.get("tool_calls", []):
        out.append(f"[tool {t['tool']}] {str(t.get('result'))[:1200]}")
    return "\n".join(out)


def fmt_flow(trace: dict[str, Any]) -> str:
    lines = [f"path: {' → '.join(trace.get('path', []))}", f"total: {trace.get('total_ms')} ms"]
    for d in trace.get("decisions", []):
        lines.append(f"- {d['node']}: [{d['predicate']}] = {d['result']} → {d['next']}  inputs={d['inputs']}")
    for t in trace.get("tool_calls", []):
        lines.append(f"- tool {t['tool']}({t['arguments']}) success={t['success']} → {str(t.get('result'))[:300]}")
    calls: dict[str, int] = {}
    for c in trace.get("llm_calls", []):
        if c.get("role") == "system":
            calls[c.get("node") or "?"] = calls.get(c.get("node") or "?", 0) + 1
    lines.append(f"LLM calls per node: {calls}")
    return "\n".join(lines)


def _tool_names() -> str:
    from agent_system.adapters.outbound.llm.tools import AVAILABLE_TOOLS

    return ", ".join(sorted(AVAILABLE_TOOLS))


def git_sha() -> str | None:
    sha = os.environ.get("GIT_SHA")
    if sha:
        return sha[:40]
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


class EvalEnv:
    def __init__(self, database: Any, kg: Any, embedder: Any, api_key: str, settings: Any) -> None:
        self.database, self.kg, self.embedder, self.api_key, self.settings = database, kg, embedder, api_key, settings

    @classmethod
    async def create(cls) -> EvalEnv:
        from agent_system.adapters.inbound.api import dependencies
        from agent_system.adapters.outbound.embedding import OpenAIEmbeddingAdapter
        from agent_system.composition_root.config import get_settings
        from agent_system.composition_root.container import get_container

        settings = get_settings()
        api_key = settings.eval_openai_api_key or settings.openai_api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("Evals need EVAL_OPENAI_API_KEY (or OPENAI_API_KEY) for the system under test")
        os.environ["OPENAI_API_KEY"] = api_key  # some extractors resolve the key from env
        container = await get_container()
        if dependencies._database is None:  # CLI: tools that open their own sessions need it
            dependencies.set_database(container.database)
        embedder = OpenAIEmbeddingAdapter(api_key=api_key)
        kg = container.knowledge_graph_adapter
        if kg is not None:
            try:
                await kg.ensure_vector_index(dimensions=embedder.get_dimensions())
            except Exception as exc:  # noqa: BLE001
                logger.warning("Vector index check failed: %s", exc)
        return cls(container.database, kg, embedder, api_key, settings)


# ---------------------------------------------------------------------------
# Agent cases
# ---------------------------------------------------------------------------


async def play_turns(case: EvalCase, seeded: Any, env: EvalEnv) -> list[dict[str, Any]]:
    from agent_system.adapters.outbound.fsm import (
        AgentDependencies,
        WorkflowState,
        run_agent_workflow,
    )
    from agent_system.adapters.outbound.persistence import (
        SQLAlchemyConversationRepository,
        SQLAlchemyPlanRepository,
        SQLAlchemyUserRepository,
    )
    from agent_system.domain.entities import Conversation
    from agent_system.domain.value_objects import Message

    turns: list[dict[str, Any]] = []
    async with env.database.session() as session:
        user_repo = SQLAlchemyUserRepository(session)
        conv_repo = SQLAlchemyConversationRepository(session)
        plan_repo = SQLAlchemyPlanRepository(session)
        user = await user_repo.get(seeded.user.id) or seeded.user
        conversation = Conversation.create(user_id=user.id)
        await conv_repo.save(conversation)
        for text in case.turns:
            conversation = conversation.add_message(Message.user(text))
            current_plan = await plan_repo.get(conversation.active_plan_id) if conversation.active_plan_id else None
            state = WorkflowState(user=user, conversation=conversation, current_plan=current_plan)
            deps = AgentDependencies(
                llm_port=None, user_repository=user_repo, conversation_repository=conv_repo,
                plan_repository=plan_repo, knowledge_graph_port=env.kg, embedding_port=env.embedder,
                openai_api_key=env.api_key, default_model=env.settings.default_model,
                fallback_model=env.settings.fallback_model, temperature=env.settings.temperature,
                max_tokens=env.settings.max_tokens, trace=TurnTrace(),
            )
            try:
                result = await run_agent_workflow(text, state, deps)
                response = result.response
            except Exception as exc:  # noqa: BLE001 - a crashing turn is a result, not a harness error
                logger.exception("case %s turn failed", case.id)
                response = f"[workflow error: {type(exc).__name__}: {exc}]"
            # the FSM may have replaced the conversation (plan activation); keep its view
            conversation = state.conversation.add_message(Message.assistant(response))
            await conv_repo.update(conversation)
            await session.commit()  # release the write lock between turns (matters on SQLite)
            user = state.user
            turns.append({"user": text, "response": response, "trace": deps.trace.to_dict()})
    return turns


async def judge_agent_case(
    case: EvalCase, suite: Suite, turns: list[dict[str, Any]], judges: list[Any],
) -> tuple[dict[str, Any], TurnTrace]:
    """Returns ({judge: {rubric: normalized}}, judge_trace)."""
    last = turns[-1]["trace"]
    context = {
        "seed": fmt_seed(case),
        "transcript": fmt_transcript(turns),
        "retrieved": fmt_retrieved(last),
        "criteria": case.expect.answer_criteria or DEFAULT_CRITERIA,
        "flow": fmt_flow(last),
        "tools": _tool_names(),
        "tool_outputs": "\n".join(f"{t['tool']}: {str(t.get('result'))[:1500]}" for t in last.get("tool_calls", [])),
    }
    rubric_names = case.rubrics if case.rubrics is not None else suite.rubrics
    judge_trace = TurnTrace()
    out: dict[str, Any] = {}
    with bind_trace(judge_trace):
        jobs = []
        for judge in judges:
            for rname in rubric_names:
                jobs.append((judge.name, rname, judge.score(judges_mod.load_rubric(rname), context)))
        results = await asyncio.gather(*(j[2] for j in jobs), return_exceptions=True)
    for (jname, rname, _), res in zip(jobs, results, strict=True):
        if isinstance(res, Exception):
            out.setdefault(jname, {})[rname] = {"error": f"{type(res).__name__}: {res}"}
        else:
            out.setdefault(jname, {})[rname] = res
    judge_trace.finish()
    return out, judge_trace


def judge_verdict(judgements: dict[str, Any], threshold: float) -> tuple[bool, list[str]]:
    """Pass when every judge's mean across rubrics clears the threshold; tag low dimensions."""
    ok = True
    tags: list[str] = []
    for rubrics in judgements.values():
        means = [r["mean"] for r in rubrics.values() if r.get("mean") is not None]
        if means and sum(means) / len(means) < threshold:
            ok = False
        for rname, r in rubrics.items():
            for dim, v in (r.get("dimensions") or {}).items():
                if v.get("score") is not None and v["score"] <= 2:
                    tags.append(f"judge:{rname}.{dim}")
    return ok, sorted(set(tags))


async def run_agent_case(case: EvalCase, suite: Suite, env: EvalEnv, judges: list[Any], run_id: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    seeded = None
    try:
        seeded = await seed_user(case, run_id, env.database, env.kg, env.embedder)
        turns = await play_turns(case, seeded, env)
        wants_kg = case.expect.entities or case.expect.forbid_entities
        snapshot = await snapshot_entities(env.kg, seeded.user.id) if wants_kg else None
        last = turns[-1]
        scores = score_agent_case(case, last["trace"], last["response"], snapshot)
        judgements, judge_trace = await judge_agent_case(case, suite, turns, judges) if judges else ({}, None)
    finally:
        if seeded is not None:
            await teardown_user(seeded, env.database, env.kg)

    det_ok = all(s.passed for s in scores)
    j_ok, j_tags = judge_verdict(judgements, suite.pass_threshold)
    errors = [t["response"] for t in turns if t["response"].startswith("[workflow error")]
    tags = sorted({s.tag for s in scores if not s.passed} | set(j_tags) | ({"error"} if errors else set()))
    costs = [t["trace"]["usage"]["cost_usd"] for t in turns]
    unpriced = sum(t["trace"]["usage"]["unpriced_calls"] for t in turns)
    return {
        "passed": det_ok and j_ok and not errors,
        "failure_tags": tags,
        "scores": {s.name: s.to_dict() for s in scores},
        "judgements": judgements,
        "turns": turns,
        "snapshot": snapshot,
        "total_ms": round(sum(t["trace"]["total_ms"] or 0 for t in turns), 1),
        "wall_ms": round((time.perf_counter() - t0) * 1000, 1),
        "cost_usd": round(sum(c for c in costs if c is not None), 6) if any(c is not None for c in costs) else None,
        "unpriced_calls": unpriced,
        "judge_cost_usd": judge_trace.usage("judge")["cost_usd"] if judge_trace else None,
        "judge_usage": judge_trace.usage("judge") if judge_trace else None,
        "error": errors[0] if errors else None,
    }


# ---------------------------------------------------------------------------
# Research cases
# ---------------------------------------------------------------------------


async def run_research_case(case: ResearchCase, suite: Suite, env: EvalEnv, judges: list[Any], run_id: str) -> dict[str, Any]:
    from agent_system.adapters.outbound.persistence import SQLAlchemyResearchRepository
    from agent_system.adapters.outbound.research.runner import (
        ResearchRunner,
        ResearchSettings,
        _LiveJob,
    )

    s = env.settings
    seeded = await seed_user(EvalCase(id=case.id, turns=["-"]), run_id, env.database, None, None)
    t0 = time.perf_counter()
    try:
        async with env.database.session() as session:
            repo = SQLAlchemyResearchRepository(session)
            job = await repo.create(str(seeded.user.id), case.question, s.default_model)
            progress = job.progress
            progress.depth = case.depth
            await repo.update_fields(job.id, progress=progress)
            await session.commit()
        runner = ResearchRunner(env.database, ResearchSettings(
            strong_model=s.default_model, fast_model=s.fallback_model, tts_model=s.tts_model, tts_voice=s.tts_voice,
            semantic_scholar_key=s.semantic_scholar_api_key, github_token=s.github_token, narrate=False,
        ))
        await runner._run(job.id, env.api_key, _LiveJob())
        async with env.database.session() as session:
            job = await SQLAlchemyResearchRepository(session).get(job.id)
        sources = [src.model_dump() for src in job.sources]
        lanes_ok = [lane for lane, lp in job.progress.lanes.items() if lp.findings > 0]
        scores = score_research_sources(case, sources, lanes_ok)
        usage = job.progress.usage or {}
        judgements: dict[str, Any] = {}
        judge_trace = TurnTrace()
        if judges and job.report_markdown:
            src_text = "\n".join(
                f"[{x.get('ref') or x['id']}] ({x['lane']}) {x['title']} — {x.get('url') or ''}\n    {x.get('snippet', '')[:400]}"
                for x in sources
            )
            ctx = {"question": case.question, "sources": src_text, "report": job.report_markdown[:30000],
                   "criteria": case.answer_criteria or ""}
            with bind_trace(judge_trace):
                for judge in judges:
                    for rname in suite.rubrics:
                        try:
                            judgements.setdefault(judge.name, {})[rname] = await judge.score(judges_mod.load_rubric(rname), ctx)
                        except Exception as exc:  # noqa: BLE001
                            judgements.setdefault(judge.name, {})[rname] = {"error": f"{type(exc).__name__}: {exc}"}
        det_ok = all(sc.passed for sc in scores)
        j_ok, j_tags = judge_verdict(judgements, suite.pass_threshold)
        failed = job.status.value == "failed"
        tags = sorted({sc.tag for sc in scores if not sc.passed} | set(j_tags) | ({"error"} if failed else set()))
        return {
            "passed": det_ok and j_ok and not failed,
            "failure_tags": tags,
            "scores": {sc.name: sc.to_dict() for sc in scores},
            "judgements": judgements,
            "turns": [{"user": case.question, "response": job.report_markdown or "",
                       "research": {"sources": sources, "usage": usage, "status": job.status.value,
                                    "lanes_with_findings": lanes_ok}}],
            "total_ms": usage.get("elapsed_ms") or round((time.perf_counter() - t0) * 1000, 1),
            "cost_usd": usage.get("cost_usd"),
            "unpriced_calls": usage.get("unpriced_calls", 0),
            "judge_cost_usd": judge_trace.usage("judge")["cost_usd"],
            "judge_usage": judge_trace.usage("judge"),
            "error": job.error,
        }
    finally:
        await teardown_user(seeded, env.database, None)


# ---------------------------------------------------------------------------
# Suite
# ---------------------------------------------------------------------------


def summarize(suite: Suite, results: list[dict[str, Any]], judge_names: list[str]) -> dict[str, Any]:
    n = len(results)
    passed = sum(1 for r in results if r["passed"])
    det: dict[str, list[float]] = {}
    for r in results:
        for name, sc in r["scores"].items():
            det.setdefault(name, []).append(sc["score"])
    judge_means: dict[str, dict[str, float]] = {}
    for jn in judge_names:
        dims: dict[str, list[int]] = {}
        for r in results:
            for rname, rub in (r["judgements"].get(jn) or {}).items():
                for dim, v in (rub.get("dimensions") or {}).items():
                    if v.get("score") is not None:
                        dims.setdefault(f"{rname}.{dim}", []).append(v["score"])
        judge_means[jn] = {k: round(sum(v) / len(v), 3) for k, v in sorted(dims.items())}
    agreement = None
    if len(judge_names) == 2:
        a, b = judge_names
        pairs = []
        for r in results:
            for rname, rub in (r["judgements"].get(a) or {}).items():
                other = (r["judgements"].get(b) or {}).get(rname) or {}
                for dim, v in (rub.get("dimensions") or {}).items():
                    ov = (other.get("dimensions") or {}).get(dim) or {}
                    pairs.append((v.get("score"), ov.get("score")))
        agreement = {"judges": [a, b], **judges_mod.agreement(pairs)}
    lat = [r["total_ms"] for r in results if r.get("total_ms") is not None]
    node_ms: dict[str, list[float]] = {}
    for r in results:
        for t in r["turns"]:
            for sp in (t.get("trace") or {}).get("spans", []):
                if sp.get("duration_ms") is not None:
                    node_ms.setdefault(sp["node"], []).append(sp["duration_ms"])
    costs = [r["cost_usd"] for r in results if r.get("cost_usd") is not None]
    jcosts = [r["judge_cost_usd"] for r in results if r.get("judge_cost_usd") is not None]
    tokens = {"input": 0, "output": 0}
    for r in results:
        for t in r["turns"]:
            u = (t.get("trace") or {}).get("usage") or (t.get("research") or {}).get("usage") or {}
            tokens["input"] += u.get("input_tokens", 0)
            tokens["output"] += u.get("output_tokens", 0)
    failure_counts: dict[str, int] = {}
    flag_counts: dict[str, int] = {}  # low judge dimensions on cases that still passed
    for r in results:
        bucket = flag_counts if r["passed"] else failure_counts
        for tag in r["failure_tags"]:
            bucket[tag] = bucket.get(tag, 0) + 1
    judge_unpriced = sum((r.get("judge_usage") or {}).get("unpriced_calls", 0) for r in results)
    return {
        "cases": n,
        "passed": passed,
        "pass_rate": round(passed / n, 3) if n else None,
        "deterministic": {k: round(sum(v) / len(v), 3) for k, v in sorted(det.items())},
        "judge": judge_means,
        "agreement": agreement,
        "latency": {
            "turn_p50_ms": percentile(lat, 0.5), "turn_p95_ms": percentile(lat, 0.95),
            "by_node": {k: {"p50": percentile(v, 0.5), "p95": percentile(v, 0.95), "n": len(v)}
                        for k, v in sorted(node_ms.items())},
        },
        "cost": {
            "system_usd": round(sum(costs), 6) if costs else None,
            "per_case_usd": round(sum(costs) / len(costs), 6) if costs else None,
            "judge_usd": round(sum(jcosts), 6) if jcosts else None,
            # cost is a lower bound when any call used a model with no known price
            "unpriced_cases": sum(1 for r in results if r.get("cost_usd") is None or r.get("unpriced_calls")),
            "unpriced_calls": sum(r.get("unpriced_calls") or 0 for r in results),
            "judge_unpriced_calls": judge_unpriced,
            "tokens": tokens,
        },
        "failure_counts": dict(sorted(failure_counts.items(), key=lambda kv: -kv[1])),
        "flag_counts": dict(sorted(flag_counts.items(), key=lambda kv: -kv[1])),
    }


async def run_suite(
    suite_name: str,
    judge: str = "openai",
    repeats: int = 1,
    concurrency: int = 2,
    case_ids: list[str] | None = None,
    run_id: str | None = None,
    progress: ProgressCb | None = None,
    analyze_failures: bool = True,
    origin: str = "cli",
) -> str:
    from agent_system.adapters.outbound.persistence import EvalCaseResultModel, EvalRunModel
    from agent_system.evals.failure_analysis import write_failure_analysis

    install_llm_capture()
    suite = load_suite(suite_name)
    env = await EvalEnv.create()
    judges = judges_mod.build_judges(judge, env.api_key) if judge != "none" else []
    judge_names = [j.name for j in judges]
    run_id = run_id or str(uuid.uuid4())

    cases: list[Any] = suite.research_cases if suite.kind == "research" else suite.cases
    if case_ids:
        cases = [c for c in cases if c.id in case_ids]
    work = [(c, rep) for c in cases for rep in range(repeats)]

    async with env.database.session() as session:
        existing = await session.get(EvalRunModel, run_id)
        if existing is None:
            session.add(EvalRunModel(
                id=run_id, suite=suite.name, judge=judge, git_sha=git_sha(), status="running",
                config={"repeats": repeats, "concurrency": concurrency, "case_ids": case_ids,
                        "model": env.settings.default_model, "fallback_model": env.settings.fallback_model,
                        "judge_models": {j.name: getattr(j, "model_name", None) for j in judges},
                        "origin": origin,
                        "total": len(work)},
            ))
        else:
            existing.status = "running"
        await session.commit()

    if env.settings.database_url.startswith("sqlite") and concurrency > 1:
        logger.warning("SQLite allows one writer at a time; running cases sequentially")
        concurrency = 1
    sem = asyncio.Semaphore(max(1, concurrency))
    results: list[dict[str, Any]] = []
    done = 0

    async def one(case: Any, rep: int) -> None:
        nonlocal done
        async with sem:
            try:
                if suite.kind == "research":
                    res = await run_research_case(case, suite, env, judges, run_id)
                else:
                    res = await run_agent_case(case, suite, env, judges, run_id)
            except Exception as exc:  # noqa: BLE001
                logger.exception("eval case %s crashed", case.id)
                res = {"passed": False, "failure_tags": ["harness_error"], "scores": {}, "judgements": {},
                       "turns": [], "total_ms": None, "cost_usd": None, "judge_cost_usd": None,
                       "error": f"{type(exc).__name__}: {exc}"}
            res["case_id"], res["repeat"] = case.id, rep
            results.append(res)
            async with env.database.session() as session:
                session.add(EvalCaseResultModel(
                    id=str(uuid.uuid4()), run_id=run_id, case_id=case.id, repeat=rep, passed=res["passed"],
                    failure_tags=res["failure_tags"], case=case.model_dump(), scores=res["scores"],
                    judgements={**res["judgements"], **({"_snapshot": res["snapshot"]} if res.get("snapshot") else {})},
                    turns=res["turns"], total_ms=res.get("total_ms"), cost_usd=res.get("cost_usd"),
                    judge_cost_usd=res.get("judge_cost_usd"), error=res.get("error"),
                ))
                await session.commit()
            done += 1
            if progress:
                await progress({"type": "case_done", "case_id": case.id, "repeat": rep, "passed": res["passed"],
                                "done": done, "total": len(work), "failure_tags": res["failure_tags"]})

    status, error = "complete", None
    try:
        await asyncio.gather(*(one(c, r) for c, r in work))
    except Exception as exc:  # noqa: BLE001
        status, error = "failed", f"{type(exc).__name__}: {exc}"

    summary = summarize(suite, results, judge_names)
    analysis = None
    if analyze_failures and any(not r["passed"] for r in results):
        try:
            analysis = await write_failure_analysis(suite, results, env.api_key)
        except Exception as exc:  # noqa: BLE001
            logger.exception("failure analysis failed")
            analysis = f"_Failure analysis could not be generated: {exc}_"

    async with env.database.session() as session:
        run = await session.get(EvalRunModel, run_id)
        run.status, run.summary, run.failure_analysis_md = status, summary, analysis
        run.error, run.completed_at = error, datetime.utcnow()
        await session.commit()
    if progress:
        await progress({"type": "run_done", "status": status, "summary": summary})
    return run_id
