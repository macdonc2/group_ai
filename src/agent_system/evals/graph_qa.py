"""Evals for the graph explorer agent.

Unlike the FSM suites, these need no database or Neo4j: the agent runs against
the synthetic graph in `graph_fixtures/graph_qa.yaml`, and every check is
deterministic (answer mentions, highlighted nodes, tools used, step budget,
returned view filter). `score_case` is pure so it is unit-tested directly.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from agent_system.application.services.graph_explorer import GraphSnapshot

FIXTURE = Path(__file__).parent / "graph_fixtures" / "graph_qa.yaml"

_REFUSAL_MARKERS = ("not in", "no record", "doesn't", "does not", "don't", "do not", "couldn't", "could not",
                    "no information", "nothing", "isn't", "is not", "no dentist", "not have", "unable")


class GraphExpect(BaseModel):
    mentions: list[str] = Field(default_factory=list)
    not_mentions: list[str] = Field(default_factory=list)
    highlight: list[str] = Field(default_factory=list)
    tools_any: list[str] = Field(default_factory=list)
    max_tool_calls: int | None = None
    node_types: list[str] | None = None
    edge_types: list[str] | None = None
    refusal: bool = False


class GraphCase(BaseModel):
    id: str
    question: str
    selected: str | None = None
    expect: GraphExpect = Field(default_factory=GraphExpect)


class GraphSuite(BaseModel):
    name: str
    description: str = ""
    graph: dict[str, list[dict[str, Any]]]
    cases: list[GraphCase]

    def snapshot(self) -> GraphSnapshot:
        return GraphSnapshot.from_records(self.graph.get("nodes", []), self.graph.get("edges", []))


def load_graph_suite(path: Path = FIXTURE) -> GraphSuite:
    return GraphSuite.model_validate(yaml.safe_load(path.read_text()))


def score_case(case: GraphCase, result: dict[str, Any]) -> dict[str, bool]:
    """Named pass/fail checks for one result (`GraphAskResult.to_dict()`)."""
    exp = case.expect
    answer = (result.get("answer") or "").lower().replace("\u2019", "'")
    tools = [s["tool"] for s in result.get("steps") or []]
    view = result.get("filter") or {}
    checks: dict[str, bool] = {"answered": result.get("stopped") == "answered"}
    if exp.mentions:
        checks["mentions"] = all(m.lower() in answer for m in exp.mentions)
    if exp.not_mentions:
        checks["not_mentions"] = not any(m.lower() in answer for m in exp.not_mentions)
    if exp.highlight:
        checks["highlight"] = set(exp.highlight) <= set(result.get("highlight_node_ids") or [])
    if exp.tools_any:
        checks["tools"] = any(t in tools for t in exp.tools_any)
    if exp.max_tool_calls is not None:
        checks["step_budget"] = len(tools) <= exp.max_tool_calls
    if exp.node_types is not None:
        checks["node_filter"] = sorted(view.get("node_types") or []) == sorted(exp.node_types)
    if exp.edge_types is not None:
        checks["edge_filter"] = sorted(view.get("edge_types") or []) == sorted(exp.edge_types)
    if exp.refusal:
        checks["refusal"] = any(m in answer for m in _REFUSAL_MARKERS)
    return checks


async def run_graph_qa(
    *, model: Any, case_ids: list[str] | None = None, repeats: int = 1, concurrency: int = 4, max_requests: int = 8,
) -> dict[str, Any]:
    from agent_system.adapters.outbound.llm.graph_agent import ask_graph

    suite = load_graph_suite()
    snapshot = suite.snapshot()
    cases = [c for c in suite.cases if not case_ids or c.id in case_ids]
    gate = asyncio.Semaphore(concurrency)

    async def one(case: GraphCase, repeat: int) -> dict[str, Any]:
        async with gate:
            result = (await ask_graph(
                snapshot, case.question, model=model, selected_id=case.selected, max_requests=max_requests,
            )).to_dict()
        checks = score_case(case, result)
        return {
            "case_id": case.id, "repeat": repeat, "passed": all(checks.values()), "checks": checks,
            "answer": result["answer"], "tools": [s["tool"] for s in result["steps"]], "usage": result["usage"],
        }

    results = await asyncio.gather(*(one(c, r) for c in cases for r in range(repeats)))
    passed = sum(r["passed"] for r in results)
    return {
        "suite": suite.name,
        "cases": len(results),
        "passed": passed,
        "pass_rate": round(passed / len(results), 3) if results else None,
        "avg_tool_calls": round(sum(len(r["tools"]) for r in results) / len(results), 2) if results else None,
        "avg_duration_ms": round(sum(r["usage"]["duration_ms"] for r in results) / len(results)) if results else None,
        "tokens": sum(r["usage"]["input_tokens"] + r["usage"]["output_tokens"] for r in results),
        "results": results,
    }
