"""A baseline kept in a file instead of the database.

`--baseline <run_id>` compares against a run stored in the same database. A CI
job starts from an empty database every time, so it has no earlier run to name.
The paired comparison only needs each case's pass/fail per attempt, which is a
few hundred bytes per suite, so that is written to a JSON file the job carries
from one run to the next:

    run --export out.json            record each suite's result in the file
    run --baseline-file base.json    compare each suite against the file

Pure functions; reading and writing the file is the only I/O.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

VERSION = 1


def load(path: str | Path) -> dict[str, dict[str, Any]]:
    """Suite name -> entry. A missing, empty or unreadable file is no baseline, not an error:
    the first run of a new job has nothing to compare against."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("version") != VERSION:
        return {}
    suites = data.get("suites")
    return suites if isinstance(suites, dict) else {}


def entry(run_id: str, git_sha: str | None, summary: dict[str, Any],
          attempts: dict[str, list[bool]]) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "git_sha": git_sha,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "pass_rate": summary.get("pass_rate"),
        "cases": len(attempts),
        "attempts": {case: list(results) for case, results in sorted(attempts.items())},
    }


def save(path: str | Path, suite: str, new_entry: dict[str, Any]) -> None:
    """Set one suite's entry, keeping the other suites already in the file."""
    suites = load(path)
    suites[suite] = new_entry
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": VERSION, "suites": suites}, indent=1, sort_keys=True) + "\n")


def attempts_of(baseline_entry: dict[str, Any]) -> dict[str, list[bool]]:
    return {str(case): [bool(x) for x in results]
            for case, results in (baseline_entry.get("attempts") or {}).items()}
