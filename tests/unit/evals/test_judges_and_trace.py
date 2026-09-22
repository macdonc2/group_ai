"""Rubric rendering, judge normalisation, agreement stats and trace usage/cost math."""

import json

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from agent_system.adapters.outbound.telemetry import LLMCall, TurnTrace, bind_trace, install_llm_capture, price_usd
from agent_system.adapters.outbound.telemetry import trace as trace_mod
from agent_system.evals import judges

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("name", judges.list_rubrics())
def test_rubrics_parse_and_render(name):
    r = judges.load_rubric(name)
    assert 3 <= len(r.dimensions) <= 5
    for levels in r.dimensions.values():
        assert set(levels) == {1, 3, 5}
    text = r.render(seed="S", transcript="T", retrieved="R", criteria="C", flow="F", tools="x",
                    tool_outputs="O", question="Q", sources="SRC", report="REP")
    assert "$" not in text.split("RUBRIC")[0], "unfilled placeholder"
    for dim in r.dimensions:
        assert dim in text


async def test_judge_with_test_model_normalises():
    rubric = judges.load_rubric("memory_retrieval")
    judge = judges._AgentJudge(TestModel())
    out = await judge.score(rubric, {"seed": "x"})
    assert set(out["dimensions"]) == set(rubric.dimensions)
    # TestModel's generated dimension names won't match, so they're reported unscored rather than invented
    assert out["mean"] is None or 1 <= out["mean"] <= 5


def test_normalize_matches_dimensions():
    rubric = judges.load_rubric("task_completion")
    j = judges.Judgement(scores=[
        judges.DimensionScore(dimension="goal_achieved", score=5, rationale="done"),
        judges.DimensionScore(dimension="Correctness", score=3, rationale="minor"),
    ], summary="ok")
    out = judges.normalize(rubric, j)
    assert out["dimensions"]["correctness"]["score"] == 3
    assert out["dimensions"]["helpfulness"]["score"] is None
    assert out["mean"] == 4.0


def test_agreement():
    perfect = judges.agreement([(5, 5), (3, 3), (1, 1), (4, 4)])
    assert perfect["exact"] == 1.0 and perfect["weighted_kappa"] == 1.0
    off = judges.agreement([(5, 4), (3, 3), (1, 2), (4, 5)])
    assert off["within_1"] == 1.0 and 0 < off["weighted_kappa"] < 1
    assert judges.agreement([(None, 3)])["n"] == 0


def test_price_usd_config_and_genai_prices(monkeypatch):
    trace_mod._configured_prices.cache_clear()
    monkeypatch.setattr(trace_mod, "_configured_prices", lambda: {"gpt-6-astra": {"input": 2.0, "cached_input": 0.5, "output": 10.0}})
    assert price_usd("openai:gpt-6-astra", 1_000_000, 100_000, cached_tokens=200_000) == pytest.approx(1.6 + 0.1 + 1.0)
    assert price_usd("gpt-5-mini", 1_000_000, 0) == pytest.approx(0.25)  # from genai-prices
    assert price_usd("totally-unknown-model", 10, 10) is None


def test_trace_usage_rollup_and_per_node():
    t = TurnTrace(user_input="hi")
    t.enter_node("AnalyzeIntent")
    t.add_llm_call(LLMCall("AnalyzeIntent", "intent", "m", 100, 10, 0, 50.0, 0.001, t.now_ms()))
    t.add_llm_call(LLMCall("AnalyzeIntent", "judge", "m", 999, 99, 0, 5.0, 0.5, t.now_ms(), role="judge"))
    t.enter_node("GenerateResponse")
    t.add_llm_call(LLMCall("GenerateResponse", "coordinator", "m", 300, 60, 0, 80.0, None, t.now_ms()))
    t.add_decision("CheckPlan", "p", False, "ExecutePlan", {"x": 1})
    t.finish("done")
    d = t.to_dict()
    json.dumps(d)  # must be JSON-serialisable for the JSON columns
    assert d["path"] == ["AnalyzeIntent", "GenerateResponse"]
    assert d["usage"]["input_tokens"] == 400 and d["usage"]["unpriced_calls"] == 1
    assert d["usage"]["cost_usd"] == pytest.approx(0.001)
    assert d["judge_usage"]["input_tokens"] == 999
    assert d["spans"][0]["input_tokens"] == 100  # judge call not billed to the node


async def test_llm_capture_attributes_calls_to_trace():
    install_llm_capture()
    t = TurnTrace()
    with bind_trace(t):
        t.enter_node("AnalyzeIntent")
        trace_mod.set_current_node("AnalyzeIntent")
        await Agent(TestModel(), name="intent").run("hello")
    assert len(t.llm_calls) == 1
    call = t.llm_calls[0]
    assert call.node == "AnalyzeIntent" and call.agent == "intent" and call.input_tokens > 0
    # nothing bound -> nothing recorded, and no error
    await Agent(TestModel()).run("unbound")
    assert len(t.llm_calls) == 1
