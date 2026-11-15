"""The outside monitor: what it reports, and how it keeps the alert issue in step.

The monitor is a repository script, not part of the installed app, so it is not in the backend
image. These tests are skipped there (the in-image CI job mounts only `tests/`) and run in the
ordinary backend job.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "prod_monitor.py"
pytestmark = [pytest.mark.unit, pytest.mark.skipif(not SCRIPT.exists(), reason="scripts/ is not shipped in the image")]

if SCRIPT.exists():
    _spec = importlib.util.spec_from_file_location("prod_monitor", SCRIPT)
    monitor = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(monitor)


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
