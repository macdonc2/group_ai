#!/usr/bin/env python3
"""Check production from outside and keep one GitHub issue in step with what it finds.

Run by .github/workflows/monitor.yml every few minutes. It asks two questions:

1. Is the site up?            GET /health/ready   (retried, so one dropped request is not an outage)
2. Is the agent in trouble?   GET /health/alerts  (the app judges its own recent chat turns)

and then makes the open "production alert" issue match the answer: opens one when something is
wrong, comments when what is wrong changes, closes it on recovery. GitHub emails the assignee
on each of those, which is the alert. Nothing is done while the state is unchanged, so a long
outage is one email, not one every few minutes.

Standard library only. `decide` and `check` take their I/O as arguments so they are unit-tested
without the network or GitHub.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

LABEL = "prod-alert"
MARKER = re.compile(r"<!-- prod-alert codes: ([a-z_,]*) -->")
Fetch = Callable[[str], tuple[int | None, str]]


def http_get(url: str, timeout: float = 15.0) -> tuple[int | None, str]:
    """(status, body). Status is None when there was no HTTP answer at all."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "prod-monitor"}), timeout=timeout) as r:  # noqa: S310
            return r.status, r.read(20000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(20000).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - DNS, TLS, timeout, refused: all "no answer"
        return None, type(exc).__name__


def check(base_url: str, fetch: Fetch = http_get, tries: int = 3, wait_s: float = 20.0,
          sleep: Callable[[float], None] = time.sleep) -> list[dict[str, str]]:
    """The problems found, as [{code, summary}]. Empty means healthy."""
    status: int | None = None
    body = ""
    for attempt in range(tries):
        status, body = fetch(f"{base_url}/health/ready")
        if status == 200:
            break
        if attempt < tries - 1:
            sleep(wait_s)
    if status is None:
        return [{"code": "site_down", "summary": f"No answer from {base_url}/health/ready after {tries} tries ({body})."}]
    if status != 200:
        return [{"code": "not_ready", "summary": f"/health/ready returned {status} after {tries} tries: {body[:300]}"}]

    status, body = fetch(f"{base_url}/health/alerts")
    if status == 404:
        return []  # an older deploy without the endpoint: uptime is still covered
    try:
        data = json.loads(body) if status == 200 else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return [{"code": "alerts_unreadable", "summary": f"/health/alerts returned {status} and no usable JSON."}]
    return [{"code": str(a.get("code")), "summary": str(a.get("summary"))} for a in data.get("alerts") or []]


def codes_of(problems: list[dict[str, str]]) -> str:
    return ",".join(sorted(p["code"] for p in problems))


def decide(problems: list[dict[str, str]], open_issue: dict[str, Any] | None) -> str:
    """What to do with the alert issue: open, update, close or nothing."""
    if not problems:
        return "close" if open_issue else "nothing"
    if not open_issue:
        return "open"
    recorded = MARKER.search(open_issue.get("body") or "")
    return "nothing" if recorded and recorded.group(1) == codes_of(problems) else "update"


def issue_body(base_url: str, problems: list[dict[str, str]], when: str) -> str:
    lines = [f"Automated check of {base_url} at {when}.", "", "| Problem | What it means |", "|---|---|"]
    lines += [f"| `{p['code']}` | {p['summary'].replace('|', '/')} |" for p in problems]
    lines += ["", "This issue closes itself when the check passes again. The numbers behind an alert are in the "
              "backend log as `alert_firing` events; see docs/observability.md.", "",
              f"<!-- prod-alert codes: {codes_of(problems)} -->"]
    return "\n".join(lines)


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout  # noqa: S603, S607


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="Base URL of the site, no trailing slash")
    parser.add_argument("--assignee", help="GitHub login to assign the alert issue to (they get the email)")
    parser.add_argument("--dry-run", action="store_true", help="Check and print; do not touch GitHub")
    args = parser.parse_args()

    problems = check(args.url.rstrip("/"))
    when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    print(json.dumps({"healthy": not problems, "problems": problems}, indent=2))
    if args.dry_run:
        return 0

    found = json.loads(gh("issue", "list", "--label", LABEL, "--state", "open", "--json", "number,body", "--limit", "1") or "[]")
    open_issue = found[0] if found else None
    action = decide(problems, open_issue)
    print(f"action: {action}")
    if action == "open":
        gh("label", "create", LABEL, "--color", "B60205", "--description", "Production is down or alerting", "--force")
        cmd = ["issue", "create", "--label", LABEL, "--title", f"Production alert: {codes_of(problems)}",
               "--body", issue_body(args.url, problems, when)]
        if args.assignee:
            cmd += ["--assignee", args.assignee]
        gh(*cmd)
    elif action == "update":
        number = str(open_issue["number"])
        body = issue_body(args.url, problems, when)
        gh("issue", "edit", number, "--title", f"Production alert: {codes_of(problems)}", "--body", body)
        gh("issue", "comment", number, "--body", f"The problems changed at {when}: `{codes_of(problems)}`. Details are in the issue description.")
    elif action == "close":
        number = str(open_issue["number"])
        gh("issue", "comment", number, "--body", f"Recovered: the check passed at {when}.")
        gh("issue", "close", number)
    return 0


if __name__ == "__main__":
    sys.exit(main())
