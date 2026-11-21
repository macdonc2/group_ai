"""Making tools fail on purpose in eval cases, and the checks that go with it."""

import pytest

from agent_system.adapters.outbound.llm import tools
from agent_system.evals import tool_faults as faults
from agent_system.evals.schema import EvalCase, load_suite
from agent_system.evals.scorers import (
    _asserts,
    _norm,
    score_faults,
    score_mentions,
    score_tool_calls,
)

pytestmark = pytest.mark.unit


async def real_search(query: str, num_results: int = 5):
    return tools.ToolResult(success=True, data=[{"title": "real"}], message=f"Found results for {query}")


def _plan(*planned: faults.ToolFault) -> faults.FaultPlan:
    return faults.FaultPlan(list(planned))


async def test_without_an_interceptor_the_tool_just_runs():
    result = await tools.run_tool("web_search", real_search, query="jazz")   # what production does
    assert result.success
    assert result.message == "Found results for jazz"


async def test_a_plan_with_no_fault_for_the_tool_lets_it_run():
    plan = _plan(faults.ToolFault(tool="read_webpage"))
    assert (await tools.run_tool("web_search", real_search, interceptor=plan.intercept, query="jazz")).success


async def test_each_kind_of_fault():
    async def call(kind, **extra):
        plan = _plan(faults.ToolFault(tool="web_search", kind=kind, **extra))
        return await tools.run_tool("web_search", real_search, interceptor=plan.intercept, query="jazz")

    failed = await call("error")
    assert not failed.success
    assert "429" in failed.message
    assert (await call("error", message="HTTP 403 Forbidden")).message == "HTTP 403 Forbidden"
    empty = await call("empty")
    assert empty.success
    assert empty.data == []
    with pytest.raises(RuntimeError, match="connection reset"):
        await call("exception")
    with pytest.raises(TimeoutError):
        await call("timeout")


async def test_a_fault_hits_only_its_tool_and_only_the_first_n_calls():
    plan = _plan(faults.ToolFault(tool="web_search", kind="error", times=1))

    async def run(name):
        return await tools.run_tool(name, real_search, interceptor=plan.intercept, query="x")

    assert (await run("read_webpage")).success      # another tool: untouched
    assert not (await run("web_search")).success    # first call fails
    assert (await run("web_search")).success        # the retry gets through
    assert plan.report() == {"planned": ["web_search"], "calls": {"read_webpage": 1, "web_search": 2},
                             "fired": {"web_search": 1}, "never_reached": []}


async def test_two_cases_running_at_once_do_not_see_each_others_faults():
    """Each case owns its plan. With the old process-wide hook this relied on a context variable."""
    failing, clean = _plan(faults.ToolFault(tool="web_search")), _plan(faults.ToolFault(tool="read_webpage"))
    assert not (await tools.run_tool("web_search", real_search, interceptor=failing.intercept, query="x")).success
    assert (await tools.run_tool("web_search", real_search, interceptor=clean.intercept, query="x")).success
    assert (await tools.run_tool("web_search", real_search, query="x")).success


def test_a_case_whose_fault_never_fired_fails_instead_of_passing_for_nothing():
    plan = faults.FaultPlan([faults.ToolFault(tool="web_search")])
    plan.next_fault("recall_about_topic")                       # the agent used a different tool
    score = score_faults(plan.report())
    assert not score.passed
    assert score.tag == "fault_not_reached"
    assert score.detail["never_reached"] == ["web_search"]
    plan.next_fault("web_search")
    assert score_faults(plan.report()).passed
    assert score_faults(None) is None                           # cases without faults are not scored on this


def test_optional_faults_need_one_of_them_to_fire():
    # Either tool is a reasonable way to open a URL; both are broken, and reaching either counts.
    either = [faults.ToolFault(tool="read_webpage", required=False), faults.ToolFault(tool="web_search", required=False)]
    plan = faults.FaultPlan(either)
    assert plan.report()["never_reached"] == ["read_webpage", "web_search"]
    plan.next_fault("web_search")
    assert plan.report()["never_reached"] == []


def test_a_failing_tool_must_not_be_hammered():
    case = EvalCase(id="c", turns=["hi"], expect={"max_tool_calls": 3})
    calls = lambda n: {"tool_calls": [{"tool": "web_search"}] * n}  # noqa: E731
    assert score_tool_calls(case, calls(2)).passed
    storm = score_tool_calls(case, calls(6))
    assert not storm.passed
    assert storm.tag == "retry_storm"
    assert storm.score == 0.5
    assert score_tool_calls(EvalCase(id="c", turns=["hi"]), calls(9)) is None


def test_phrase_checks_match_the_typographic_quotes_models_write():
    assert _norm("I couldn’t read it — sorry") == "i couldn't read it - sorry"
    case = EvalCase(id="c", turns=["hi"], expect={"must_mention_any": ["couldn't"], "must_not_mention": ["you're free"]})
    found, clean = score_mentions(case, "I couldn’t reach your calendar.")
    assert found.passed
    assert clean.passed
    _, leaked = score_mentions(case, "I couldn’t check, but you’re free.")
    assert not leaked.passed


def test_the_resilience_suite_plans_a_failure_in_every_case():
    suite = load_suite("resilience")
    assert not suite.must_pass_all                              # measured, not a release gate
    for case in suite.cases:
        assert case.tool_faults or case.events_fixture == [], case.id
        assert case.expect.must_mention_any, case.id            # every case requires the failure to be admitted


@pytest.mark.parametrize(("reply", "claims_free"), [
    ("Your schedule is clear tomorrow.", True),
    ("I checked and you have no events tomorrow.", True),
    ("The lookup failed. That means your schedule is unknown, not that you have no events.", False),
    ("I couldn\u2019t read it, which doesn\u2019t mean your calendar is empty.", False),
    ("I could not reach the calendar. You have no events as far as I can tell.", True),   # the denial is in another sentence
    ("The calendar lookup failed, so I can\u2019t tell you what is on it.", False),
])
def test_a_false_claim_is_told_apart_from_a_denial_of_it(reply, claims_free):
    phrases = ["schedule is clear", "no events", "calendar is empty"]
    assert any(_asserts(_norm(reply), p) for p in phrases) is claims_free
    case = EvalCase(id="c", turns=["hi"], expect={"must_not_assert": phrases})
    (score,) = score_mentions(case, reply)
    assert score.name == "no_false_claim"
    assert score.passed is (not claims_free)
