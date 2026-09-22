"""CLI: python -m agent_system.evals {list,run}"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys


def _print_summary(run_id: str, summary: dict) -> None:
    print(f"\nrun {run_id}")
    print(f"  pass rate: {summary.get('passed')}/{summary.get('cases')} ({summary.get('pass_rate')})")
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
    finally:
        await shutdown_container()
    return code


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
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
