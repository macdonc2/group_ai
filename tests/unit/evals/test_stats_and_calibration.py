"""Uncertainty on eval results, and agreement between the graders and a person."""

from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agent_system.evals import stats
from agent_system.evals.calibration import HARNESS, OVERALL, calibrate, rows_for_result
from agent_system.evals.runner import summarize
from agent_system.evals.schema import load_suite

pytestmark = pytest.mark.unit


def attempts(**cases: str) -> dict[str, list[bool]]:
    """`a="PPF"` is case a passing twice then failing."""
    return {c: [ch == "P" for ch in pattern] for c, pattern in cases.items()}


# --- intervals -------------------------------------------------------------


def test_wilson_is_wide_on_few_cases_and_never_zero_width_at_the_edges():
    low, high = stats.wilson(9, 10)
    assert round(low, 2) == 0.60 and round(high, 2) == 0.98      # "90%" on 10 cases could be 60%
    low, high = stats.wilson(10, 10)
    assert round(high, 6) == 1.0 and round(low, 2) == 0.72               # a clean sweep still has a floor
    assert stats.wilson(0, 0) is None
    wide, narrow = stats.wilson(9, 10), stats.wilson(90, 100)
    assert narrow[1] - narrow[0] < wide[1] - wide[0]


def test_one_attempt_per_case_uses_wilson():
    ci = stats.pass_rate_interval({str(i): [i < 9] for i in range(10)})
    assert (ci["low"], ci["high"], ci["method"], ci["cases"]) == (0.596, 0.982, "wilson", 10)


def test_repeats_do_not_count_as_extra_cases():
    # Four cases tried five times each is still four cases of evidence, not twenty.
    per_case = attempts(a="PPPPP", b="PPPPP", c="FFFFF", d="PPFPP")
    ci = stats.pass_rate_interval(per_case)
    assert ci["method"] == "case_bootstrap" and ci["cases"] == 4
    naive = stats.wilson(14, 20)
    assert ci["high"] - ci["low"] > naive[1] - naive[0]
    assert ci == stats.pass_rate_interval(per_case)              # seeded: same input, same numbers


def test_identical_cases_fall_back_to_an_interval_on_the_case_count():
    ci = stats.pass_rate_interval(attempts(a="PPP", b="PPP", c="PPP"))
    assert ci["method"] == "wilson_on_cases" and ci["high"] == 1.0 and ci["low"] < 0.5
    assert stats.pass_rate_interval({}) is None


# --- consistency -----------------------------------------------------------


def test_consistency_separates_reliable_from_lucky():
    con = stats.consistency(attempts(a="PPP", b="PFP", c="FFF", d="PPP"))
    assert con == {"k": 3, "pass_all_k": 0.5, "pass_any": 0.75, "always_fail": ["c"], "flaky": ["b"], "flaky_rate": 0.25}
    assert stats.consistency(attempts(a="P", b="F")) is None     # one attempt says nothing about repeatability


# --- paired comparison -----------------------------------------------------


def test_a_real_improvement_is_called_better():
    a = {str(i): [i < 5] for i in range(20)}
    b = {str(i): [i < 14] for i in range(20)}
    cmp = stats.paired_comparison(a, b)
    assert cmp["verdict"] == "better" and cmp["difference"] == 0.45 and cmp["interval"]["low"] > 0
    assert cmp["p_value"] < 0.01 and len(cmp["improved"]) == 9 and cmp["worsened"] == []
    assert stats.paired_comparison(b, a)["verdict"] == "worse"


def test_one_case_flipping_is_not_a_difference():
    a = {str(i): [i < 8] for i in range(10)}
    b = {str(i): [i < 9] for i in range(10)}                     # 80% -> 90% looks like progress
    cmp = stats.paired_comparison(a, b)
    assert cmp["difference"] == 0.1 and cmp["verdict"] == "no_clear_difference" and cmp["p_value"] == 1.0


def test_five_one_way_flips_in_ten_cases_is_still_not_enough():
    # 40% -> 80% with nothing worse. The bootstrap interval alone would call it; the exact test (p = 2/32) does not.
    a = {str(i): [i < 4] for i in range(10)}
    b = {str(i): [i < 9] for i in range(10)}
    cmp = stats.paired_comparison(a, b)
    assert cmp["difference"] == 0.5 and cmp["interval"]["low"] > 0
    assert cmp["p_value"] == pytest.approx(2 / 32, abs=1e-4) and cmp["verdict"] == "no_clear_difference"


def test_swapped_failures_cancel_out():
    cmp = stats.paired_comparison(attempts(a="P", b="F", c="P"), attempts(a="F", b="P", c="P"))
    assert cmp["difference"] == 0 and cmp["verdict"] == "no_clear_difference"
    assert (cmp["improved"], cmp["worsened"]) == (["b"], ["a"])


def test_only_shared_cases_are_compared():
    cmp = stats.paired_comparison(attempts(a="P", old="F"), attempts(a="P", new="F"))
    assert cmp["shared_cases"] == 1 and cmp["only_in_a"] == ["old"] and cmp["only_in_b"] == ["new"]
    assert stats.paired_comparison(attempts(a="P"), attempts(b="P"))["verdict"] == "no_shared_cases"


def test_the_sign_flip_test_matches_mcnemar_on_single_attempts():
    # 6 cases changed, all in one direction: exact two-sided p = 2 / 2^6.
    assert stats._sign_flip_p([1.0] * 6 + [0.0] * 4) == pytest.approx(2 / 64)
    assert stats._sign_flip_p([0.0, 0.0]) == 1.0


def test_run_summary_carries_the_interval_and_consistency():
    result = lambda cid, ok: {"case_id": cid, "passed": ok, "scores": {}, "judgements": {}, "turns": [],  # noqa: E731
                              "failure_tags": [] if ok else ["wrong_tool"], "total_ms": 10.0}
    summary = summarize(load_suite("routing"), [result("a", True), result("a", False), result("b", True), result("b", True)], [])
    assert (summary["cases"], summary["distinct_cases"], summary["pass_rate"]) == (4, 2, 0.75)
    assert summary["pass_rate_interval"]["method"] == "case_bootstrap"
    assert summary["consistency"]["pass_all_k"] == 0.5 and summary["consistency"]["flaky"] == ["a"]


# --- calibration -----------------------------------------------------------


def judge_row(human: bool, mean: float, i: int = 0) -> dict:
    return {"grader": "openai", "rubric": "task_completion", "human": human, "mean": mean, "threshold": 3.5,
            "result_id": f"r{i}", "run_id": "run", "case_id": f"case{i}", "note": ""}


def test_a_lenient_judge_looks_fine_on_agreement_but_misses_failures():
    # 40 good outputs it passes, 10 bad ones of which it catches only 3.
    rows = [judge_row(True, 4.5, i) for i in range(40)] + [judge_row(False, 2.0, 40 + i) for i in range(3)] \
        + [judge_row(False, 4.0, 43 + i) for i in range(7)]
    (g,) = calibrate(rows)
    assert g["agreement"] == 0.86 and g["catches_failures"] == 0.3 and g["passes_good"] == 1.0
    assert g["status"] == "unreliable"
    assert g["confusion"] == {"both_pass": 40, "both_fail": 3, "missed_failure": 7, "false_alarm": 0}
    assert len(g["disagreements"]) == 7 and g["disagreements"][0]["grader_mean"] == 4.0
    by_t = {t["threshold"]: t for t in g["by_threshold"]}
    assert by_t[4.5]["catches_failures"] == 1.0                  # a stricter cut-off would have caught them


def test_a_judge_that_matches_the_person_is_trustworthy_once_there_are_enough_labels():
    rows = [judge_row(True, 4.2, i) for i in range(25)] + [judge_row(False, 2.4, 25 + i) for i in range(10)]
    (g,) = calibrate(rows)
    assert (g["agreement"], g["kappa"], g["status"]) == (1.0, 1.0, "trustworthy")
    (few,) = calibrate(rows[:20])                                # all passes, and too few
    assert few["status"] == "needs_more_labels" and few["catches_failures"] is None


def test_overall_labels_check_the_harness_and_rubric_labels_check_each_judge():
    result = {"id": "r1", "run_id": "run", "case_id": "plan_trip", "passed": True,
              "judgements": {"openai": {"task_completion": {"mean": 4.0}, "agent_flow": {"mean": 2.0}},
                             "jev": {"task_completion": {"mean": 3.0}}, "_snapshot": {"people": []}}}
    labels = {OVERALL: {"passed": False, "note": "wrong restaurant"}, "task_completion": {"passed": True, "note": ""}}
    rows = rows_for_result(result, labels, 3.5)
    assert sorted((r["grader"], r["rubric"]) for r in rows) == [
        ("harness", "overall"), ("jev", "task_completion"), ("openai", "task_completion")]
    by = {(g["grader"], g["rubric"]): g for g in calibrate(rows)}
    assert by[(HARNESS, OVERALL)]["confusion"]["missed_failure"] == 1
    assert by[(HARNESS, OVERALL)]["disagreements"][0]["note"] == "wrong restaurant"
    assert by[("openai", "task_completion")]["agreement"] == 1.0 and by[("jev", "task_completion")]["agreement"] == 0.0
    assert "by_threshold" not in by[(HARNESS, OVERALL)]


# --- the label and calibration routes --------------------------------------


@pytest.fixture
async def session():
    from agent_system.adapters.outbound.persistence import EvalCaseResultModel, EvalRunModel
    from agent_system.adapters.outbound.persistence.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        s.add(EvalRunModel(id="run", suite="e2e_tasks", judge="openai", status="complete"))
        s.add(EvalCaseResultModel(id="r1", run_id="run", case_id="plan_trip", passed=True,
                                  judgements={"openai": {"task_completion": {"mean": 4.0}}}))
        await s.commit()
        yield s
    await engine.dispose()


async def test_labels_are_saved_changed_removed_and_reported(session):
    from fastapi import HTTPException

    from agent_system.adapters.inbound.api.routes import evals as routes

    me = SimpleNamespace(user_id="u1")
    await routes.set_label("r1", "overall", routes.LabelIn(passed=False, note="wrong restaurant"), me, session)
    out = await routes.set_label("r1", "task_completion", routes.LabelIn(passed=True), me, session)
    assert out["labels"] == {"overall": {"passed": False, "note": "wrong restaurant"},
                             "task_completion": {"passed": True, "note": ""}}
    assert (await routes.get_case_result("r1", me, session))["labels"] == out["labels"]

    report = await routes.calibration(me, session)
    assert (report["labelled_results"], report["labels"]) == (1, 2)
    by = {(g["grader"], g["rubric"]): g for g in report["graders"]}
    assert by[("harness", "overall")]["confusion"]["missed_failure"] == 1
    assert by[("openai", "task_completion")]["agreement"] == 1.0
    assert (await routes.calibration(me, session, suite="routing"))["graders"] == []

    await routes.set_label("r1", "overall", routes.LabelIn(passed=True, note=""), me, session)      # change
    out = await routes.set_label("r1", "task_completion", routes.LabelIn(passed=None), me, session)  # remove
    assert out["labels"] == {"overall": {"passed": True, "note": ""}}

    with pytest.raises(HTTPException) as bad:
        await routes.set_label("r1", "not_a_rubric", routes.LabelIn(passed=True), me, session)
    assert bad.value.status_code == 400
    with pytest.raises(HTTPException) as missing:
        await routes.set_label("nope", "overall", routes.LabelIn(passed=True), me, session)
    assert missing.value.status_code == 404
