"""CLI: python -m agent_system.evals {list,run}"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys


def _print_summary(run_id: str, summary: dict) -> None:
    print(f"\nrun {run_id}")
    ci = summary.get("pass_rate_interval")
    band = f"  95% interval {ci['low']} to {ci['high']} over {ci['cases']} cases" if ci else ""
    print(f"  pass rate: {summary.get('passed')}/{summary.get('cases')} ({summary.get('pass_rate')}){band}")
    gate = summary.get("gate")
    if gate:
        print("  HARD GATE: " + ("passed, every case passed" if gate["passed"]
                                 else f"FAILED on {', '.join(gate['failed_cases']) or 'no cases run'}"))
    con = summary.get("consistency")
    if con:
        print(f"  consistency over {con['k']} attempts: passed every time {con['pass_all_k']}, "
              f"at least once {con['pass_any']}, mixed results {con['flaky_rate']}")
        if con["flaky"]:
            print(f"    mixed: {', '.join(con['flaky'])}")
    for name, v in (summary.get("deterministic") or {}).items():
        print(f"  {name:<22} {v}")
    for judge, dims in (summary.get("judge") or {}).items():
        print(f"  judge {judge}:")
        for dim, v in dims.items():
            print(f"    {dim:<40} {v}")
    if summary.get("agreement"):
        print(f"  judge agreement: {summary['agreement']}")
    lat, cost = summary.get("latency") or {}, summary.get("cost") or {}
    print(f"  latency p50/p95: {lat.get('turn_p50_ms')} / {lat.get('turn_p95_ms')} ms")
    lb = " (lower bound)" if cost.get("unpriced_calls") else ""
    print(f"  cost: system ${cost.get('system_usd')}{lb}  judge ${cost.get('judge_usd')}  tokens {cost.get('tokens')}")
    if cost.get("unpriced_calls") or cost.get("judge_unpriced_calls"):
        print(f"  ! {cost.get('unpriced_calls')} system + {cost.get('judge_unpriced_calls')} judge LLM calls used models "
              "with no known price; set MODEL_PRICING_JSON")
    if summary.get("failure_counts"):
        print(f"  failures: {json.dumps(summary['failure_counts'])}")
    if summary.get("flag_counts"):
        print(f"  flags on passing cases: {json.dumps(summary['flag_counts'])}")
    by_node = (lat.get("by_node") or {})
    if by_node:
        slow = sorted(by_node.items(), key=lambda kv: -(kv[1].get("p50") or 0))[:4]
        print("  slowest nodes (p50): " + ", ".join(f"{k} {v['p50']}ms" for k, v in slow))


async def _run(args: argparse.Namespace) -> int:
    from agent_system.adapters.outbound.persistence import EvalRunModel
    from agent_system.composition_root.container import get_container, shutdown_container
    from agent_system.evals import baseline_file
    from agent_system.evals.runner import run_suite

    logging.getLogger().setLevel(logging.WARNING)  # app modules configure INFO on import
    for name in ("agent_system", "httpx", "neo4j"):
        logging.getLogger(name).setLevel(logging.WARNING)

    async def progress(ev: dict) -> None:
        if ev["type"] == "case_done":
            mark = "PASS" if ev["passed"] else "FAIL " + ",".join(ev["failure_tags"])
            print(f"[{ev['done']}/{ev['total']}] {ev['case_id']}#{ev['repeat']}: {mark}", flush=True)

    suites = args.suite
    code = 0
    try:
        for suite in suites:
            run_id = await run_suite(
                suite, judge=args.judge, repeats=args.repeats, concurrency=args.concurrency,
                case_ids=args.case or None, progress=progress, analyze_failures=not args.no_analysis,
            )
            container = await get_container()
            async with container.database.session() as session:
                run = await session.get(EvalRunModel, run_id)
                _print_summary(run_id, run.summary)
                if run.failure_analysis_md and args.show_analysis:
                    print("\n" + run.failure_analysis_md)
                if run.status != "complete" or (args.fail_under is not None and (run.summary.get("pass_rate") or 0) < args.fail_under):
                    code = 1
                if (run.summary.get("gate") or {}).get("passed") is False:
                    code = 1
                if args.baseline:
                    code = max(code, await _compare_with(session, args.baseline, run_id, args.fail_on_regression))
                if args.baseline_file or args.export:
                    attempts = await _attempts(session, run_id)
                    if args.baseline_file:
                        code = max(code, _compare_with_file(args.baseline_file, suite, run_id, attempts,
                                                            args.fail_on_regression))
                    # an interrupted or errored run is not a result worth comparing against later
                    if args.export and run.status == "complete":
                        baseline_file.save(args.export, suite,
                                           baseline_file.entry(run_id, run.git_sha, run.summary, attempts))
    finally:
        await shutdown_container()
    return code


async def _attempts(session, run_id: str) -> dict[str, list[bool]]:
    from sqlalchemy import select

    from agent_system.adapters.outbound.persistence import EvalCaseResultModel
    from agent_system.evals import stats

    rows = (await session.execute(select(EvalCaseResultModel.case_id, EvalCaseResultModel.passed)
                                  .where(EvalCaseResultModel.run_id == run_id))).all()
    return stats.group_by_case({"case_id": c, "passed": ok} for c, ok in rows)


async def _compare_with(session, baseline: str, run_id: str, fail_on_regression: bool) -> int:
    """Print the paired comparison against `baseline`; return 1 if it is clearly worse and that should fail."""
    from agent_system.evals import stats

    paired = stats.paired_comparison(await _attempts(session, baseline), await _attempts(session, run_id))
    _print_paired(baseline, run_id, paired)
    return 1 if fail_on_regression and paired["verdict"] == "worse" else 0


def _compare_with_file(path: str, suite: str, run_id: str, attempts: dict[str, list[bool]],
                       fail_on_regression: bool) -> int:
    """Like `_compare_with`, but the baseline is a suite entry in a file written by `--export`."""
    from agent_system.evals import baseline_file, stats

    base = baseline_file.load(path).get(suite)
    if not base:
        print(f"\nno baseline for {suite} in {path}; nothing to compare against")
        return 0
    paired = stats.paired_comparison(baseline_file.attempts_of(base), attempts)
    label = f"{base.get('run_id')} (commit {(base.get('git_sha') or 'unknown')[:9]}, {base.get('recorded_at')})"
    _print_paired(label, run_id, paired)
    return 1 if fail_on_regression and paired["verdict"] == "worse" else 0


def _print_paired(a: str, b: str, paired: dict) -> None:
    print(f"\ncompare {b} against baseline {a}")
    if paired["verdict"] == "no_shared_cases":
        print("  the two runs share no cases")
        return
    ci = paired["interval"]
    print(f"  shared cases: {paired['shared_cases']}  pass rate {paired['pass_rate_a']} -> {paired['pass_rate_b']}")
    print(f"  difference: {paired['difference']:+}  95% interval {ci['low']:+} to {ci['high']:+}  p = {paired['p_value']}")
    print("  verdict: " + {"better": "better than the baseline", "worse": "worse than the baseline",
                           "no_clear_difference": "no clear difference on this evidence"}[paired["verdict"]])
    for label, key in (("improved", "improved"), ("worsened", "worsened")):
        if paired[key]:
            print(f"  {label}: {', '.join(paired[key])}")


async def _compare(args: argparse.Namespace) -> int:
    from agent_system.composition_root.container import get_container, shutdown_container

    try:
        container = await get_container()
        async with container.database.session() as session:
            return await _compare_with(session, args.baseline, args.run, args.fail_on_regression)
    finally:
        await shutdown_container()


async def _calibration(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from agent_system.adapters.outbound.persistence import EvalCaseResultModel, EvalHumanLabelModel, EvalRunModel
    from agent_system.composition_root.container import get_container, shutdown_container
    from agent_system.evals.calibration import calibrate, rows_for_result
    from agent_system.evals.schema import list_suites, load_suite

    try:
        container = await get_container()
        async with container.database.session() as session:
            found = (await session.execute(
                select(EvalHumanLabelModel, EvalCaseResultModel, EvalRunModel.suite)
                .join(EvalCaseResultModel, EvalCaseResultModel.id == EvalHumanLabelModel.result_id)
                .join(EvalRunModel, EvalRunModel.id == EvalCaseResultModel.run_id))).all()
    finally:
        await shutdown_container()
    thresholds = {n: load_suite(n).pass_threshold for n in list_suites()}
    by_result: dict[str, dict] = {}
    for label, result, suite in found:
        if args.suite and suite != args.suite:
            continue
        e = by_result.setdefault(result.id, {"result": {"id": result.id, "run_id": result.run_id, "case_id": result.case_id,
                                                        "passed": result.passed, "judgements": result.judgements},
                                             "suite": suite, "labels": {}})
        e["labels"][label.rubric] = {"passed": label.passed, "note": label.note}
    rows = [r for e in by_result.values() for r in rows_for_result(e["result"], e["labels"], thresholds.get(e["suite"], 3.5))]
    graders = calibrate(rows)
    if not graders:
        print("No human labels yet. Label case results in the Evals tab (Scores & judges), then run this again.")
        return 0
    print(f"{'grader':<10} {'rubric':<24} {'n':>4} {'agree':>6} {'catches fails':>14} {'passes good':>12} {'kappa':>6}  status")
    for g in graders:
        fmt = lambda v: "-" if v is None else f"{v:.2f}"  # noqa: E731
        print(f"{g['grader']:<10} {g['rubric']:<24} {g['n']:>4} {fmt(g['agreement']):>6} {fmt(g['catches_failures']):>14} "
              f"{fmt(g['passes_good']):>12} {fmt(g['kappa']):>6}  {g['status']}")
    return 0


async def _run_graph_qa(args: argparse.Namespace) -> int:
    from agent_system.adapters.outbound.llm.agents import _get_model
    from agent_system.composition_root.config import get_settings
    from agent_system.evals.graph_qa import run_graph_qa

    s = get_settings()
    key = s.eval_openai_api_key or s.openai_api_key
    if not key:
        print("Set EVAL_OPENAI_API_KEY or OPENAI_API_KEY to run graph-qa.")
        return 2
    model = _get_model(args.model or s.graph_agent_model or s.default_model, key)
    summary = await run_graph_qa(model=model, case_ids=args.case or None, repeats=args.repeats,
                                 concurrency=args.concurrency, max_requests=s.graph_agent_max_requests)
    for r in summary["results"]:
        failed = [k for k, ok in r["checks"].items() if not ok]
        mark = "PASS" if r["passed"] else "FAIL " + ",".join(failed)
        print(f"{r['case_id']}#{r['repeat']}: {mark}  tools={r['tools']}  {round(r['usage']['duration_ms'])}ms")
        if not r["passed"] or args.verbose:
            print(f"    answer: {r['answer'][:300]}")
    print(f"\npass rate: {summary['passed']}/{summary['cases']} ({summary['pass_rate']})  "
          f"avg tool calls {summary['avg_tool_calls']}  avg {summary['avg_duration_ms']}ms  tokens {summary['tokens']}")
    if args.fail_under is not None and (summary["pass_rate"] or 0) < args.fail_under:
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m agent_system.evals")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="List suites and rubrics")
    run = sub.add_parser("run", help="Run one or more suites")
    run.add_argument("--suite", action="append", required=True, help="Suite name (repeatable)")
    run.add_argument("--judge", choices=["openai", "jev", "both", "none"], default="openai")
    run.add_argument("--repeats", type=int, default=1)
    run.add_argument("--concurrency", type=int, default=2)
    run.add_argument("--case", action="append", help="Only these case ids (repeatable)")
    run.add_argument("--no-analysis", action="store_true", help="Skip the LLM failure write-up")
    run.add_argument("--show-analysis", action="store_true", help="Print the failure analysis markdown")
    run.add_argument("--fail-under", type=float, help="Exit 1 when pass rate is below this (CI gate)")
    run.add_argument("--baseline", help="Run id to compare against, paired by case")
    run.add_argument("--fail-on-regression", action="store_true",
                     help="With --baseline or --baseline-file: exit 1 when the run is clearly worse "
                          "(interval on the difference below zero)")
    run.add_argument("--baseline-file", help="Compare each suite against its entry in this file (written by --export)")
    run.add_argument("--export", help="Record each suite's per-case results in this file, for a later --baseline-file")
    cmp_ = sub.add_parser("compare", help="Paired comparison of two stored runs")
    cmp_.add_argument("baseline")
    cmp_.add_argument("run")
    cmp_.add_argument("--fail-on-regression", action="store_true")
    cal = sub.add_parser("calibration", help="Agreement between the graders and the human labels")
    cal.add_argument("--suite")
    gq = sub.add_parser("graph-qa", help="Run the graph explorer agent against the synthetic graph fixture")
    gq.add_argument("--case", action="append", help="Only these case ids (repeatable)")
    gq.add_argument("--repeats", type=int, default=1)
    gq.add_argument("--concurrency", type=int, default=4)
    gq.add_argument("--model", help="Override the model, e.g. openai:gpt-5.6-luna")
    gq.add_argument("--verbose", action="store_true", help="Print every answer, not just failures")
    gq.add_argument("--fail-under", type=float, help="Exit 1 when pass rate is below this (CI gate)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    if args.cmd == "list":
        from agent_system.evals.judges import list_rubrics
        from agent_system.evals.schema import list_suites, load_suite

        for name in list_suites():
            s = load_suite(name)
            n = len(s.research_cases) if s.kind == "research" else len(s.cases)
            print(f"{name:<20} {s.kind:<8} {n:>3} cases  rubrics={','.join(s.rubrics)}  {s.description}")
        print(f"\nrubrics: {', '.join(list_rubrics())}")
        return
    if args.cmd == "compare":
        sys.exit(asyncio.run(_compare(args)))
    if args.cmd == "calibration":
        sys.exit(asyncio.run(_calibration(args)))
    if args.cmd == "graph-qa":
        sys.exit(asyncio.run(_run_graph_qa(args)))
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
