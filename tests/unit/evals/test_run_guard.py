"""Stopping an eval run that is wasting money or scoring a dead model."""

from types import SimpleNamespace

import pytest

from agent_system.adapters.outbound.telemetry import trace as trace_mod
from agent_system.evals import runner
from agent_system.evals.runner import RunGuard, summarize
from agent_system.evals.schema import load_suite

pytestmark = pytest.mark.unit


def result(tokens: int, cost: float | None = 0.10, judge_cost: float | None = None):
    return {"passed": tokens > 0, "failure_tags": [], "scores": {}, "judgements": {}, "total_ms": 10.0,
            "cost_usd": cost, "judge_cost_usd": judge_cost,
            "turns": [{"user": "hi", "response": "ok", "trace": {"usage": {"input_tokens": tokens}}}]}


def test_a_run_stops_starting_cases_once_the_spend_cap_is_reached():
    guard = RunGuard(max_cost_usd=0.25)
    assert guard.observe(result(12000, cost=0.10)) is False
    assert guard.stop is None
    guard.observe(result(12000, cost=0.10, judge_cost=0.06))      # judge spend counts too: 0.26 in total
    assert guard.stop.startswith("the spend cap of $0.25 was reached ($0.26 spent)")


def test_no_cap_and_unpriced_cases_never_stop_the_run_on_cost():
    guard = RunGuard(max_cost_usd=0)
    for _ in range(50):
        guard.observe(result(12000, cost=5.0))
    assert guard.stop is None
    capped = RunGuard(max_cost_usd=1.0)
    capped.observe(result(12000, cost=None))                      # a model with no known price
    assert capped.stop is None
    assert capped.spent_usd == 0


def test_cases_from_a_dead_model_are_discarded_and_two_in_a_row_stop_the_run():
    # What an account with no credits looks like: no crash, just "failed" cases with zero tokens.
    guard = RunGuard(max_cost_usd=5.0)
    assert guard.observe(result(0, cost=None)) is True
    assert guard.stop is None
    assert guard.observe(result(9000)) is False
    assert guard.dead_in_a_row == 0
    assert guard.observe(result(0, cost=None)) is True
    assert guard.observe(result(0, cost=None)) is True
    assert "model calls are failing" in guard.stop
    assert "credits" in guard.stop


def test_a_harness_crash_is_not_mistaken_for_a_dead_model():
    guard = RunGuard()
    crash = {"passed": False, "failure_tags": ["harness_error"], "turns": [], "cost_usd": None, "judge_cost_usd": None}
    assert guard.observe(crash) is False
    assert guard.observe(crash) is False
    assert guard.stop is None


def test_research_cases_count_their_own_usage():
    research = {"turns": [{"user": "q", "response": "r", "research": {"usage": {"input_tokens": 40000}}}]}
    assert runner._input_tokens(research) == 40000
    assert runner._input_tokens({"turns": []}) == 0


def test_a_stopped_run_with_no_results_still_summarises():
    summary = summarize(load_suite("routing"), [], [])
    assert summary["cases"] == 0
    assert summary["pass_rate"] is None
    assert summary["pass_rate_interval"] is None


async def test_preflight_explains_why_the_model_cannot_be_called(monkeypatch):
    import pydantic_ai

    env = SimpleNamespace(api_key="sk-test", settings=SimpleNamespace(default_model="openai:gpt-6-astra"))

    def agent_that(outcome):
        class FakeAgent:
            def __init__(self, model):
                pass

            async def run(self, prompt):
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
        return FakeAgent

    monkeypatch.setattr("agent_system.adapters.outbound.llm.agents._get_model", lambda model, key: object())
    monkeypatch.setattr(pydantic_ai, "Agent", agent_that("OK"))
    assert await runner.model_preflight(env) is None

    monkeypatch.setattr(pydantic_ai, "Agent", agent_that(RuntimeError("429 insufficient_quota: You have no credits remaining")))
    why = await runner.model_preflight(env)
    assert "openai:gpt-6-astra" in why
    assert "no credits left" in why

    monkeypatch.setattr(pydantic_ai, "Agent", agent_that(RuntimeError("401 invalid_api_key")))
    assert "API key was rejected" in await runner.model_preflight(env)


def test_the_default_model_has_a_price_so_cost_is_never_silently_missing(monkeypatch):
    monkeypatch.setattr(trace_mod, "_configured_prices", lambda: {})
    # 1M input of which 800k cached, 100k output, at $10 / $1 / $50 per 1M
    assert trace_mod.price_usd("openai:gpt-6-astra", 1_000_000, 100_000, 800_000) == pytest.approx(2.0 + 0.8 + 5.0)
    assert trace_mod.price_usd("some-model-nobody-knows", 1000, 1000) is None
    # a configured price still wins over the built-in one
    monkeypatch.setattr(trace_mod, "_configured_prices", lambda: {"gpt-6-astra": {"input": 1.0, "output": 2.0}})
    assert trace_mod.price_usd("gpt-6-astra", 1_000_000, 1_000_000) == pytest.approx(3.0)
