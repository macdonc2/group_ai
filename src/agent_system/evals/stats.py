"""Uncertainty for eval results: intervals, consistency across repeats, paired run comparison.

Three ideas, all pure functions over per-case outcomes:

- A pass rate from a few dozen cases is an estimate. `pass_rate_interval` puts a 95% interval
  on it. Repeats of one case are not independent of each other (the same case tends to pass or
  fail every time), so with repeats the unit of resampling is the case, not the attempt.
- An agent that passes a case two times in three is not reliable on it. `consistency` reports
  pass^k (the share of cases that passed every one of k attempts) next to the plain rate, and
  names the cases that gave mixed results.
- Two runs of the same suite share their cases, so the comparison is paired: the question is
  whether the per-case differences lean one way, not whether two independent rates differ.
  `paired_comparison` gives the mean difference, its interval and a sign-flip permutation p-value.

Everything random is seeded, so the same results always give the same numbers.
"""

from __future__ import annotations

import itertools
import math
import random
from typing import Any, Iterable

Z95 = 1.959964
ALPHA = 0.05
_BOOTSTRAP_DRAWS = 4000
_PERMUTATION_DRAWS = 20000
_EXACT_PERMUTATION_MAX = 16  # 2^16 sign patterns; above this, sample
_SEED = 20261115


def group_by_case(results: Iterable[dict[str, Any]]) -> dict[str, list[bool]]:
    """Case id -> the pass/fail of each attempt at it."""
    out: dict[str, list[bool]] = {}
    for r in results:
        out.setdefault(str(r["case_id"]), []).append(bool(r["passed"]))
    return out


def wilson(passed: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """Wilson score interval for a proportion. Unlike the normal approximation it stays inside
    [0, 1] and is not zero-width at 0% or 100%, which matters with few cases."""
    if n <= 0:
        return None
    p = passed / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _quantiles(values: list[float], lo: float = 0.025, hi: float = 0.975) -> tuple[float, float]:
    values = sorted(values)
    pick = lambda q: values[min(len(values) - 1, max(0, int(round(q * (len(values) - 1)))))]  # noqa: E731
    return pick(lo), pick(hi)


def pass_rate_interval(per_case: dict[str, list[bool]]) -> dict[str, Any] | None:
    """95% interval on the pass rate, with the method used.

    One attempt per case: Wilson. Several: a bootstrap that resamples whole cases, so repeats
    of one case do not count as independent evidence. If every case gave the same rate the
    bootstrap has nothing to resample, so the Wilson interval on the number of cases is used.
    """
    rates = [sum(v) / len(v) for v in per_case.values() if v]
    if not rates:
        return None
    n = len(rates)
    mean = sum(rates) / n
    single = all(len(v) == 1 for v in per_case.values())
    if single or len(set(rates)) == 1:
        lo, hi = wilson(round(mean * n), n)  # type: ignore[misc]
        method = "wilson" if single else "wilson_on_cases"
    else:
        rng = random.Random(_SEED)
        draws = [sum(rng.choices(rates, k=n)) / n for _ in range(_BOOTSTRAP_DRAWS)]
        lo, hi = _quantiles(draws)
        method = "case_bootstrap"
    return {"low": round(lo, 3), "high": round(hi, 3), "level": 0.95, "method": method, "cases": n}


def consistency(per_case: dict[str, list[bool]]) -> dict[str, Any] | None:
    """How repeatable the results are. Only meaningful with two or more attempts per case."""
    k = min((len(v) for v in per_case.values()), default=0)
    if k < 2:
        return None
    n = len(per_case)
    flaky = sorted(c for c, v in per_case.items() if 0 < sum(v) < len(v))
    return {
        "k": k,
        "pass_all_k": round(sum(all(v) for v in per_case.values()) / n, 3),   # pass^k: reliable cases
        "pass_any": round(sum(any(v) for v in per_case.values()) / n, 3),     # passed at least once
        "always_fail": sorted(c for c, v in per_case.items() if not any(v)),
        "flaky": flaky,
        "flaky_rate": round(len(flaky) / n, 3),
    }


def _sign_flip_p(diffs: list[float]) -> float:
    """Two-sided p-value for 'the mean difference is zero' by flipping the sign of each case's
    difference. With one attempt per case this is the exact McNemar test."""
    nonzero = [d for d in diffs if d != 0]
    if not nonzero:
        return 1.0
    observed = abs(sum(nonzero))
    if len(nonzero) <= _EXACT_PERMUTATION_MAX:
        hits = total = 0
        for signs in itertools.product((1, -1), repeat=len(nonzero)):
            total += 1
            hits += abs(sum(s * d for s, d in zip(signs, nonzero, strict=True))) >= observed - 1e-12
        return hits / total
    rng = random.Random(_SEED)
    hits = sum(abs(sum(d if rng.random() < 0.5 else -d for d in nonzero)) >= observed - 1e-12
               for _ in range(_PERMUTATION_DRAWS))
    return (hits + 1) / (_PERMUTATION_DRAWS + 1)


def paired_comparison(a: dict[str, list[bool]], b: dict[str, list[bool]]) -> dict[str, Any]:
    """Compare run `b` against baseline `a` on the cases both ran.

    `verdict` is "better" or "worse" only when the interval on the difference excludes zero and
    the permutation p-value is below 0.05; otherwise the two runs are "no_clear_difference" on
    this evidence, however the raw rates look. Both are required because the bootstrap interval
    is too narrow on a handful of cases, where the exact test is the stricter of the two.
    """
    shared = sorted(set(a) & set(b))
    out: dict[str, Any] = {"shared_cases": len(shared), "only_in_a": sorted(set(a) - set(b)),
                           "only_in_b": sorted(set(b) - set(a))}
    if not shared:
        return {**out, "verdict": "no_shared_cases"}
    rate = lambda v: sum(v) / len(v)  # noqa: E731
    diffs = [rate(b[c]) - rate(a[c]) for c in shared]
    n = len(diffs)
    mean = sum(diffs) / n
    if len(set(diffs)) == 1:
        lo = hi = mean
    else:
        rng = random.Random(_SEED)
        lo, hi = _quantiles([sum(rng.choices(diffs, k=n)) / n for _ in range(_BOOTSTRAP_DRAWS)])
    p = _sign_flip_p(diffs)
    clear = p < ALPHA
    verdict = "better" if lo > 0 and clear else "worse" if hi < 0 and clear else "no_clear_difference"
    return {
        **out,
        "pass_rate_a": round(sum(rate(a[c]) for c in shared) / n, 3),
        "pass_rate_b": round(sum(rate(b[c]) for c in shared) / n, 3),
        "difference": round(mean, 3),
        "interval": {"low": round(lo, 3), "high": round(hi, 3), "level": 0.95, "method": "paired_case_bootstrap"},
        "p_value": round(p, 4),
        "improved": sorted(c for c, d in zip(shared, diffs, strict=True) if d > 0),
        "worsened": sorted(c for c, d in zip(shared, diffs, strict=True) if d < 0),
        "verdict": verdict,
    }
