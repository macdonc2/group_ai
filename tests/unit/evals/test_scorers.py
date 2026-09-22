"""Deterministic eval scorers against hand-built traces."""

import pytest

from agent_system.evals.schema import EvalCase, ExpectedEntity, list_suites, load_suite
from agent_system.evals.scorers import (
    is_subsequence,
    percentile,
    score_agent_case,
    score_entities,
    score_recall,
    score_route,
    score_tool,
    score_tool_args,
)

pytestmark = pytest.mark.unit

TOOL_PATH = ["ReceiveInput", "AnalyzeIntent", "UpdateKnowledge", "CheckPlan", "ExecutePlan",
             "SelectTool", "ExecuteTool", "EvaluateResult", "GenerateResponse", "FinalizeKnowledge"]


def trace(**kw):
    base = {"path": TOOL_PATH, "decisions": [], "retrievals": [], "tool_calls": [], "total_ms": 1200.0,
            "usage": {"cost_usd": None}}
    base.update(kw)
    return base


def case(**expect):
    return EvalCase(id="c", turns=["hi"], expect=expect)


def test_subsequence():
    assert is_subsequence(["AnalyzeIntent", "SelectTool"], TOOL_PATH)
    assert not is_subsequence(["SelectTool", "AnalyzeIntent"], TOOL_PATH)


def test_route_order_and_forbidden():
    ok = score_route(case(route=["CheckPlan", "SelectTool"], forbid_nodes=["CreatePlan"]), trace())
    assert ok.passed and ok.score == 1.0
    bad = score_route(case(route=["CreatePlan"], forbid_nodes=["SelectTool"]), trace())
    assert not bad.passed and bad.detail["forbidden_hit"] == ["SelectTool"]
    assert score_route(case(), trace()) is None


def test_tool_and_args():
    t = trace(tool_calls=[{"tool": "recall_about_topic", "arguments": {"topic": "Zane hobbies"}, "result": "x", "success": True}])
    assert score_tool(case(tool="recall_about_topic"), t).passed
    assert not score_tool(case(tool="none"), t).passed
    assert score_tool(case(tool="none"), trace()).passed
    args = score_tool_args(case(tool="recall_about_topic", tool_args={"topic": "zane"}), t)
    assert args.passed
    miss = score_tool_args(case(tool="recall_about_topic", tool_args={"topic": "rachel"}), t)
    assert not miss.passed and miss.detail["missing"] == {"topic": "rachel"}


def test_recall_ranks_and_context():
    t = trace(retrievals=[
        {"source": "semantic_search", "query": "q", "hits": [
            {"content": "knee is sore", "used_in_prompt": True},
            {"content": "cold brew after 3pm", "used_in_prompt": True},
        ]},
        {"source": "entity_lookup", "query": "Rachel", "hits": [{"content": "hates cilantro", "used_in_prompt": False}]},
    ])
    s = score_recall(case(must_recall=["cold brew", "cilantro"]), t)
    assert s.detail["facts"]["cold brew"]["best_rank"] == 2
    assert s.detail["facts"]["cilantro"]["retrieved"] and not s.detail["facts"]["cilantro"]["in_context"]
    assert s.score == 0.5 and not s.passed
    assert s.detail["mrr"] == pytest.approx((0.5 + 1.0) / 2)


def test_recall_counts_tool_output_as_context():
    t = trace(tool_calls=[{"tool": "recall_about_topic", "arguments": {}, "result": "Zane is allergic to shellfish", "success": True}])
    assert score_recall(case(must_recall=["shellfish"]), t).passed


def test_entities_alias_split_and_relationship():
    snap = {"person": [{"name": "Dominique", "aliases": ["Dom"], "relationship_type": "friend"}], "pet": [], "location": []}
    c = case(entities=[ExpectedEntity(type="person", name="Dominique", aliases=["Dom"], relationship_type="friend")])
    res = {s.name: s for s in score_entities(c, snap)}
    assert res["entity_resolution"].passed and res["entity_dedup"].passed

    split = {"person": [{"name": "Dominique", "aliases": []}, {"name": "Dom", "aliases": []}], "pet": [], "location": []}
    res = {s.name: s for s in score_entities(c, split)}
    assert not res["entity_resolution"].passed
    assert not res["entity_dedup"].passed and res["entity_dedup"].detail["duplicated"] == ["Dominique"]


def test_forbidden_entities():
    c = case(forbid_entities=["Pixel"])
    res = score_entities(c, {"person": [], "pet": [{"name": "Pixel"}], "location": []})
    assert res[0].name == "no_spurious_entities" and not res[0].passed


def test_score_agent_case_combines():
    t = trace(decisions=[{"node": "AnalyzeIntent", "predicate": "p", "result": True, "next": "UpdateKnowledge",
                          "inputs": {"intent": "question"}}])
    scores = {s.name: s for s in score_agent_case(
        case(intent="question", must_mention=["tacos"], must_not_mention=["cilantro is great"]),
        t, "Rachel loves tacos", None)}
    assert scores["intent"].passed and scores["mentions"].passed and scores["no_hallucination"].passed


def test_percentile():
    assert percentile([1, 2, 3, 4], 0.5) == 2.5
    assert percentile([], 0.5) is None


@pytest.mark.parametrize("name", list_suites())
def test_suites_load(name):
    suite = load_suite(name)
    cases = suite.research_cases if suite.kind == "research" else suite.cases
    assert cases, name
    assert len({c.id for c in cases}) == len(cases), "duplicate case ids"
