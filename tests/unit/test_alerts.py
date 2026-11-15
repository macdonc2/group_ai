"""Alert rules over recent chat turns, and the outside monitor that acts on them."""

import importlib.util
from pathlib import Path

import pytest

from agent_system.application.services.alerts import Thresholds, TurnStat, evaluate

pytestmark = pytest.mark.unit

_spec = importlib.util.spec_from_file_location("prod_monitor", Path(__file__).parents[2] / "scripts" / "prod_monitor.py")
monitor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(monitor)


def ok(ms: float = 8000, cost: float = 0.05) -> TurnStat:
    return TurnStat(total_ms=ms, input_tokens=9000, cost_usd=cost, error=None)


def failed(how: str = "error") -> TurnStat:
    return TurnStat(total_ms=3000, input_tokens=4000, cost_usd=0.02, error=how)


DEAD = TurnStat(total_ms=900, input_tokens=0, cost_usd=None, error=None)


def codes(turns, spend_day=0.0, t=None):
    return [a.code for a in evaluate(turns, spend_day, t or Thresholds())]


# --- the rules -------------------------------------------------------------


def test_a_quiet_or_healthy_hour_raises_nothing():
    assert codes([]) == []
    assert codes([ok() for _ in range(12)]) == []


def test_one_bad_turn_is_not_an_alert_in_a_single_user_app():
    assert codes([failed()]) == []                       # 100% of one turn
    assert codes([failed(), failed(), ok()]) == []       # two failures: still below the minimum


def test_several_failed_turns_that_are_a_real_share_do_alert():
    alerts = evaluate([failed("timeout"), failed("step_limit"), failed("RuntimeError"), ok(), ok()], 0.0)
    assert [a.code for a in alerts] == ["turn_failures"]
    assert alerts[0].detail == {"failed_turns": 3, "turns": 5, "outcomes": {"timeout": 1, "step_limit": 1, "error": 1}}
    assert codes([failed(), failed(), failed()] + [ok()] * 20) == []     # three in twenty-three is not a pattern


def test_turns_with_no_model_tokens_mean_the_model_cannot_be_reached():
    # What ran out of credits looks like: the API answers, the turn "completes", no tokens were used.
    assert codes([DEAD, DEAD, ok()]) == ["model_unreachable"]
    assert codes([DEAD, ok(), ok()]) == []               # one could be a cancelled request
    assert codes([DEAD, DEAD]) == ["model_unreachable"]  # and it is not double-counted as a failure


def test_slow_turns_alert_on_the_p95_of_turns_that_succeeded():
    assert codes([ok(ms=150_000), ok(ms=160_000), ok(ms=140_000)]) == ["slow_turns"]
    assert codes([ok(ms=150_000), ok(ms=160_000)]) == []                 # too few to call it
    assert codes([ok(), ok(), ok(), ok(ms=200_000)] + [ok()] * 30) == []  # one slow turn among many


def test_spend_alerts_for_the_hour_and_the_day_and_can_be_switched_off():
    pricey = [ok(cost=2.0) for _ in range(3)]                             # $6 in the hour
    assert codes(pricey) == ["spend_hour"]
    assert codes([ok()], spend_day=25.0) == ["spend_day"]
    assert codes(pricey, spend_day=25.0, t=Thresholds(spend_hour_usd=0, spend_day_usd=0)) == []


def test_public_summaries_carry_no_numbers():
    for alert in evaluate([ok(cost=9.0), DEAD, DEAD, failed(), failed(), failed()], 99.0):
        assert not any(ch.isdigit() for ch in alert.summary.replace("24 hours", "")), alert.summary


# --- the outside monitor ---------------------------------------------------


def fetcher(responses):
    calls = []

    def fetch(url):
        calls.append(url)
        answer = responses[url.rsplit("/", 1)[-1]]
        return answer.pop(0) if isinstance(answer, list) else answer

    return fetch, calls


def test_a_healthy_site_has_no_problems():
    fetch, calls = fetcher({"ready": (200, "{}"), "alerts": (200, '{"status": "ok", "alerts": []}')})
    assert monitor.check("https://x", fetch, sleep=lambda s: None) == []
    assert calls == ["https://x/health/ready", "https://x/health/alerts"]


def test_one_dropped_request_is_retried_but_three_are_an_outage():
    fetch, calls = fetcher({"ready": [(None, "TimeoutError"), (200, "{}")], "alerts": (200, '{"alerts": []}')})
    assert monitor.check("https://x", fetch, sleep=lambda s: None) == []
    fetch, calls = fetcher({"ready": (None, "URLError")})
    (problem,) = monitor.check("https://x", fetch, sleep=lambda s: None)
    assert problem["code"] == "site_down"
    assert len(calls) == 3


def test_not_ready_and_app_alerts_are_reported():
    fetch, _ = fetcher({"ready": (503, '{"status": "not_ready", "checks": {"database": "down"}}')})
    (problem,) = monitor.check("https://x", fetch, sleep=lambda s: None)
    assert problem["code"] == "not_ready"
    assert "database" in problem["summary"]

    body = '{"status": "alerting", "alerts": [{"code": "model_unreachable", "summary": "Check credits."}]}'
    fetch, _ = fetcher({"ready": (200, "{}"), "alerts": (200, body)})
    assert monitor.check("https://x", fetch) == [{"code": "model_unreachable", "summary": "Check credits."}]


def test_an_older_deploy_without_the_alerts_endpoint_is_not_an_alert_but_garbage_is():
    fetch, _ = fetcher({"ready": (200, "{}"), "alerts": (404, "Not Found")})
    assert monitor.check("https://x", fetch) == []
    fetch, _ = fetcher({"ready": (200, "{}"), "alerts": (200, "<html>")})
    assert [p["code"] for p in monitor.check("https://x", fetch)] == ["alerts_unreadable"]


def test_the_issue_is_opened_once_updated_on_change_and_closed_on_recovery():
    down = [{"code": "site_down", "summary": "No answer."}]
    spend = [{"code": "spend_hour", "summary": "Over budget."}]
    assert monitor.decide([], None) == "nothing"
    assert monitor.decide(down, None) == "open"
    issue = {"number": 7, "body": monitor.issue_body("https://x", down, "now")}
    assert monitor.decide(down, issue) == "nothing"          # still down: no second email
    assert monitor.decide(spend, issue) == "update"          # a different problem: say so
    assert monitor.decide(down + spend, issue) == "update"
    assert monitor.decide([], issue) == "close"
    assert monitor.decide(down, {"number": 8, "body": "edited by hand"}) == "update"
