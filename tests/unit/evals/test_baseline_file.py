"""The file-carried baseline that lets a CI job compare against an earlier job."""

import pytest

from agent_system.evals import baseline_file, stats
from agent_system.evals.__main__ import _compare_with_file

pytestmark = pytest.mark.unit


def _attempts(passed: int, total: int) -> dict[str, list[bool]]:
    return {f"case_{i}": [i < passed] for i in range(total)}


def test_round_trip_keeps_other_suites(tmp_path):
    path = tmp_path / "nested" / "baseline.json"
    baseline_file.save(path, "routing", baseline_file.entry("run-a", "abc123", {"pass_rate": 0.9}, _attempts(9, 10)))
    baseline_file.save(path, "tool_selection", baseline_file.entry("run-b", None, {"pass_rate": 1.0}, _attempts(3, 3)))
    baseline_file.save(path, "routing", baseline_file.entry("run-c", "def456", {"pass_rate": 1.0}, _attempts(10, 10)))

    suites = baseline_file.load(path)
    assert set(suites) == {"routing", "tool_selection"}
    assert suites["routing"]["run_id"] == "run-c"
    assert suites["routing"]["cases"] == 10
    assert baseline_file.attempts_of(suites["tool_selection"]) == _attempts(3, 3)


@pytest.mark.parametrize("content", [None, "", "not json", "[]", '{"version": 99, "suites": {"routing": {}}}'])
def test_missing_or_unusable_file_is_no_baseline(tmp_path, content):
    path = tmp_path / "baseline.json"
    if content is not None:
        path.write_text(content)
    assert baseline_file.load(path) == {}


def test_first_run_has_nothing_to_compare_and_does_not_fail(tmp_path, capsys):
    code = _compare_with_file(str(tmp_path / "absent.json"), "routing", "run-now", _attempts(0, 10), True)
    assert code == 0
    assert "no baseline for routing" in capsys.readouterr().out


def test_clearly_worse_fails_only_when_asked(tmp_path, capsys):
    path = tmp_path / "baseline.json"
    baseline_file.save(path, "routing", baseline_file.entry("run-a", "abc123", {}, _attempts(12, 12)))
    now = _attempts(2, 12)
    assert stats.paired_comparison(_attempts(12, 12), now)["verdict"] == "worse"

    assert _compare_with_file(str(path), "routing", "run-now", now, fail_on_regression=True) == 1
    assert _compare_with_file(str(path), "routing", "run-now", now, fail_on_regression=False) == 0
    assert "worse than the baseline" in capsys.readouterr().out


def test_one_case_flipping_is_not_a_regression(tmp_path):
    path = tmp_path / "baseline.json"
    baseline_file.save(path, "routing", baseline_file.entry("run-a", "abc123", {}, _attempts(10, 10)))
    assert _compare_with_file(str(path), "routing", "run-now", _attempts(9, 10), fail_on_regression=True) == 0
