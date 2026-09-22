"""Group failed cases by category and write a markdown failure analysis.

The deterministic part (counts, examples, where to look) is always written;
an LLM then writes the pattern and suggested fix for each category from the
concrete evidence.
"""

from __future__ import annotations

from typing import Any

from agent_system.adapters.outbound.telemetry import llm_role
from agent_system.evals.schema import Suite

# Where each failure category usually originates in this codebase.
SUSPECTS: dict[str, str] = {
    "wrong_intent": "`AnalyzeIntent` / `INTENT_SYSTEM_PROMPT` in adapters/outbound/llm/agents.py",
    "wrong_route": "branch predicates in adapters/outbound/fsm/nodes.py (`CheckPlan`, `ExecutePlan`, `EvaluateResult`)",
    "wrong_tool": "`suggested_tool` from the intent agent; tool descriptions in `get_tools_description()` (llm/tools.py)",
    "bad_args": "`SelectTool` argument building / pronoun resolution in fsm/nodes.py",
    "missed_retrieval": "`GenerateResponse` retrieval (semantic_search min_score=0.7, top-5 cut) and `Neo4jAdapter.recall_about_topic`",
    "hallucinated_memory": "coordinator/synthesis prompts treating related-history snippets as facts",
    "incomplete_answer": "context assembly in `GenerateResponse` (200-char truncation of related history)",
    "entity_miss": "`FinalizeKnowledge` extraction (confidence ≥ 0.7 gate) and `extract_knowledge_from_text`",
    "entity_spurious": "`KNOWLEDGE_EXTRACTION_PROMPT` treating hypotheticals/pronouns as real entities",
    "entity_dup": "`Neo4jAdapter.store_person/store_pet` MERGE on exact lower-case name (no alias resolution)",
    "slow": "per-node latency in the trace — usually FinalizeKnowledge's serial extraction calls",
    "error": "workflow exception — see the case's trace `error`",
    "harness_error": "evals/runner.py or seeding",
    "thin_sources": "research/sources.py search fan-out",
    "low_diversity": "research/lanes.py `_plan_queries`",
    "lane_empty": "research/lanes.py `run_lane` (lane error or no findings)",
    "uncitable_source": "research/sources.py dedupe/assign_ids",
}


def _category(tag: str) -> str:
    return tag.split(".")[0] if tag.startswith("judge:") else tag


def _case_evidence(r: dict[str, Any], tag: str) -> str:
    lines = [f"case `{r['case_id']}` (repeat {r['repeat']})"]
    if r["turns"]:
        last = r["turns"][-1]
        lines.append(f"  user: {last['user'][:300]}")
        lines.append(f"  reply: {str(last['response'])[:500]}")
        tr = last.get("trace") or {}
        if tr:
            lines.append(f"  path: {' → '.join(tr.get('path', []))}")
            for d in tr.get("decisions", [])[:8]:
                lines.append(f"  decision {d['node']}: {d['predicate']} = {d['result']} → {d['next']}")
            for t in tr.get("tool_calls", []):
                lines.append(f"  tool {t['tool']}({t['arguments']}) → {str(t.get('result'))[:200]}")
    for s in r["scores"].values():
        if not s["passed"]:
            lines.append(f"  score {s['name']} = {s['score']}: {str(s['detail'])[:600]}")
    for jn, rubrics in r["judgements"].items():
        for rname, rub in rubrics.items():
            for dim, v in (rub.get("dimensions") or {}).items():
                if v.get("score") is not None and v["score"] <= 2:
                    lines.append(f"  judge {jn} {rname}.{dim} = {v['score']}: {v['rationale']}")
    if r.get("error"):
        lines.append(f"  error: {r['error']}")
    return "\n".join(lines)


def group_failures(results: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        if r["passed"]:
            continue
        for cat in dict.fromkeys(_category(t) for t in r["failure_tags"] or ["judge_below_threshold"]):
            groups.setdefault(cat, []).append(r)
    return dict(sorted(groups.items(), key=lambda kv: -len(kv[1])))


async def write_failure_analysis(suite: Suite, results: list[dict[str, Any]], api_key: str | None) -> str:
    groups = group_failures(results)
    failed = sum(1 for r in results if not r["passed"])
    header = [f"# Failure analysis — `{suite.name}`", "",
              f"{failed} of {len(results)} case runs failed across {len(groups)} categories.", ""]
    sections = []
    for tag, rs in groups.items():
        ids = sorted({r["case_id"] for r in rs})
        evidence = "\n\n".join(_case_evidence(r, tag) for r in rs[:4])
        analysis = await _llm_section(tag, evidence, api_key) if api_key else None
        sections.append("\n".join([
            f"## {tag} — {len(rs)} run(s)",
            f"**Cases:** {', '.join(f'`{i}`' for i in ids)}",
            f"**Where to look:** {SUSPECTS.get(tag.removeprefix('judge:').split('.')[0], SUSPECTS.get(tag, 'see the traces'))}",
            "",
            analysis or "",
            "",
            "<details><summary>Evidence</summary>\n\n```\n" + evidence[:6000] + "\n```\n</details>",
        ]))
    return "\n".join(header) + "\n\n".join(sections)


async def _llm_section(tag: str, evidence: str, api_key: str) -> str | None:
    from pydantic_ai import Agent

    from agent_system.adapters.outbound.llm.agents import _get_model
    from agent_system.composition_root.config import get_settings

    agent = Agent(
        _get_model(get_settings().eval_judge_model, api_key),
        name="failure_analyst",
        output_type=str,
        system_prompt=(
            "You analyse failed evaluation cases for an LLM agent built as a finite-state machine with a Neo4j "
            "memory graph. From the evidence, write: **Pattern** (what goes wrong, one short paragraph), "
            "**Likely cause** (point at the node, predicate, prompt or retrieval step the evidence implicates), "
            "and **Suggested fix** (concrete and small). Use only the evidence; say so when it's inconclusive. "
            "Plain markdown, no headings, under 180 words."
        ),
    )
    try:
        with llm_role("judge"):
            result = await agent.run(f"Failure category: {tag}\n\nEvidence:\n{evidence[:12000]}")
        return result.output.strip()
    except Exception as exc:  # noqa: BLE001
        return f"_Analysis unavailable: {type(exc).__name__}_"
