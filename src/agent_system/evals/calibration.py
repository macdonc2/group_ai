"""Checking the graders against a person.

An LLM judge is a model like any other: until its verdicts have been compared with a human's
on the same outputs, its scores are unvalidated. A superuser labels case results pass or fail
(per rubric, and "overall" for the case as a whole); `calibrate` then reports, for each grader,
how often it agrees with those labels.

What is compared:
- For a rubric, the judge's verdict is "its mean score on that rubric is at least the threshold".
- For "overall", the grader is the harness itself: the case's stored pass/fail, which combines
  the deterministic checks and the judges.

What is reported (a failure is the thing worth catching, so it is the positive class):
- agreement: share of labels where grader and human match. Misleading alone when most outputs pass.
- catches_failures (sensitivity): of the outputs the human failed, the share the grader failed.
- passes_good (specificity): of the outputs the human passed, the share the grader passed.
- kappa: agreement beyond what the two pass rates would give by chance.
- by_threshold: the same agreement at other cut-offs, to show whether 3.5 is the right one.
"""

from __future__ import annotations

from typing import Any

OVERALL = "overall"          # label for the whole case, compared with the harness's own pass/fail
HARNESS = "harness"
MIN_LABELS = 30              # below this the rates are too noisy to act on
MIN_PER_CLASS = 5            # and both human-pass and human-fail need some examples
THRESHOLDS = (2.5, 3.0, 3.5, 4.0, 4.5)


def _rates(pairs: list[tuple[bool, bool]]) -> dict[str, Any]:
    """`pairs` are (human_passed, grader_passed)."""
    n = len(pairs)
    both_pass = sum(h and g for h, g in pairs)
    both_fail = sum((not h) and (not g) for h, g in pairs)
    missed = sum((not h) and g for h, g in pairs)        # human failed it, grader let it through
    false_alarm = sum(h and (not g) for h, g in pairs)   # human passed it, grader failed it
    human_fail, human_pass = both_fail + missed, both_pass + false_alarm
    agree = (both_pass + both_fail) / n if n else None
    kappa = None
    if n:
        ph, pg = human_pass / n, (both_pass + missed) / n
        chance = ph * pg + (1 - ph) * (1 - pg)
        kappa = round((agree - chance) / (1 - chance), 3) if chance < 1 else None
    return {
        "n": n, "human_pass": human_pass, "human_fail": human_fail,
        "agreement": round(agree, 3) if agree is not None else None,
        "catches_failures": round(both_fail / human_fail, 3) if human_fail else None,
        "passes_good": round(both_pass / human_pass, 3) if human_pass else None,
        "kappa": kappa,
        "confusion": {"both_pass": both_pass, "both_fail": both_fail, "missed_failure": missed,
                      "false_alarm": false_alarm},
    }


def _status(r: dict[str, Any]) -> str:
    if r["n"] < MIN_LABELS or min(r["human_pass"], r["human_fail"]) < MIN_PER_CLASS:
        return "needs_more_labels"
    if (r["catches_failures"] or 0) >= 0.8 and (r["passes_good"] or 0) >= 0.8:
        return "trustworthy"
    return "unreliable"


def calibrate(rows: list[dict[str, Any]], default_threshold: float = 3.5) -> list[dict[str, Any]]:
    """One entry per (grader, rubric).

    Each row is one human label joined to one grader's output on the same case result:
    `{grader, rubric, human, grader_passed | mean, threshold?, result_id, run_id, case_id, note}`.
    Rows for a judge carry `mean`; rows for the harness carry `grader_passed`.
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["grader"], row["rubric"]), []).append(row)

    out = []
    for (grader, rubric), items in sorted(groups.items()):
        def verdict(row: dict[str, Any], threshold: float | None = None) -> bool:
            if row.get("mean") is None:
                return bool(row["grader_passed"])
            return row["mean"] >= (threshold if threshold is not None else row.get("threshold") or default_threshold)

        rates = _rates([(bool(r["human"]), verdict(r)) for r in items])
        entry = {"grader": grader, "rubric": rubric, **rates, "status": _status(rates)}
        if any(r.get("mean") is not None for r in items):
            entry["by_threshold"] = [
                {"threshold": t, **{k: v for k, v in _rates([(bool(r["human"]), verdict(r, t)) for r in items]).items()
                                    if k in ("agreement", "catches_failures", "passes_good")}}
                for t in THRESHOLDS
            ]
        entry["disagreements"] = [
            {"result_id": r["result_id"], "run_id": r.get("run_id"), "case_id": r.get("case_id"),
             "human": bool(r["human"]), "grader_mean": r.get("mean"), "note": r.get("note") or ""}
            for r in items if bool(r["human"]) != verdict(r)
        ]
        out.append(entry)
    return out


def rows_for_result(result: dict[str, Any], labels: dict[str, dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
    """Join one case result's human labels to every grader that scored it."""
    base = {"result_id": result["id"], "run_id": result.get("run_id"), "case_id": result.get("case_id")}
    rows = []
    for rubric, label in labels.items():
        common = {**base, "rubric": rubric, "human": label["passed"], "note": label.get("note")}
        if rubric == OVERALL:
            rows.append({**common, "grader": HARNESS, "grader_passed": bool(result["passed"])})
            continue
        for judge, rubrics in (result.get("judgements") or {}).items():
            if judge.startswith("_") or not isinstance(rubrics, dict):
                continue
            mean = (rubrics.get(rubric) or {}).get("mean")
            if mean is not None:
                rows.append({**common, "grader": judge, "mean": mean, "threshold": threshold})
    return rows
