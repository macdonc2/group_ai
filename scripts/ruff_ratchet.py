#!/usr/bin/env python3
"""Lint gate that only fails on findings that are new.

The repo carries a backlog of ruff findings from before CI existed. Fixing them
all at once would be a huge diff with no behaviour change, so instead the
backlog is recorded in ``.ruff-baseline.json`` as a count per file and rule,
and this script fails only when a count goes above what is recorded.

Counts, not line numbers, so editing a file does not shift old findings into
looking new. The cost is that fixing one finding and adding another of the same
rule in the same file nets to zero and passes.

    python scripts/ruff_ratchet.py            check against the baseline
    python scripts/ruff_ratchet.py --update   rewrite the baseline from the tree

Run ``--update`` after fixing findings so the lower counts become the new
ceiling. Never run it to make a new finding pass; fix the finding instead.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / ".ruff-baseline.json"


def current_counts() -> dict[str, dict[str, int]]:
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", ".", "--output-format", "json", "--exit-zero"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"ruff itself failed (exit {proc.returncode})")
    counts: Counter[tuple[str, str]] = Counter()
    for finding in json.loads(proc.stdout):
        path = Path(finding["filename"]).resolve().relative_to(ROOT).as_posix()
        # ruff reports a file it cannot parse with no rule code
        counts[(path, finding.get("code") or "syntax-error")] += 1
    nested: dict[str, dict[str, int]] = {}
    for (path, code), n in sorted(counts.items()):
        nested.setdefault(path, {})[code] = n
    return nested


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--update", action="store_true", help="rewrite the baseline")
    args = parser.parse_args()

    now = current_counts()
    total_now = sum(sum(rules.values()) for rules in now.values())

    if args.update:
        BASELINE.write_text(json.dumps(now, indent=1, sort_keys=True) + "\n")
        print(f"Baseline written: {total_now} findings in {len(now)} files.")
        return 0

    base: dict[str, dict[str, int]] = json.loads(BASELINE.read_text())
    total_base = sum(sum(rules.values()) for rules in base.values())

    worse = []
    for path, rules in now.items():
        for code, n in rules.items():
            allowed = base.get(path, {}).get(code, 0)
            if n > allowed:
                worse.append((path, code, allowed, n))

    if worse:
        print("New ruff findings (count is above the recorded baseline):\n")
        for path, code, allowed, n in worse:
            print(f"  {path}: {code} {allowed} -> {n}")
        files = sorted({path for path, *_ in worse})
        codes = ",".join(sorted({code for _, code, *_ in worse if code != "syntax-error"}))
        select = f" --select {codes}" if codes else ""
        print(f"\nSee them with:\n  ruff check{select} {' '.join(files)}")
        print("Fix the new ones. Do not raise the baseline to make this pass.")
        return 1

    print(f"ruff: no new findings ({total_now} recorded as backlog, baseline {total_base}).")
    if total_now < total_base:
        print(
            f"{total_base - total_now} fewer than the baseline. "
            "Run `python scripts/ruff_ratchet.py --update` and commit to lock that in."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
