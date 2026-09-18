#!/usr/bin/env -S uv run python
"""Quick test of the ReAct planning trigger - run locally to verify requires_planning.

CheckPlan enters ReAct reasoning mode when the intent agent sets requires_planning
(or the intent is a task). Reasoning mode bypasses the tool chosen by AnalyzeIntent,
so a query that a tool can answer must NOT set requires_planning.

Usage:
    uv run scripts/test_planning_trigger.py
    # Or with explicit text:
    uv run scripts/test_planning_trigger.py "How do I make sourdough starter?"
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

# Load .env from project root
_project_root = os.path.join(os.path.dirname(__file__), "..")
load_dotenv(os.path.join(_project_root, ".env"))

# Add src to path
sys.path.insert(0, os.path.join(_project_root, "src"))

from agent_system.adapters.outbound.llm import create_intent_agent

MODEL = os.getenv("DEFAULT_MODEL", "openai:gpt-6-astra")

# (query, expected requires_planning)
PROBES: list[tuple[str, bool]] = [
    # Multi-phase reasoning: should plan
    ("How do I make sourdough starter?", True),
    ("Why does my bread come out dense and how do I fix it?", True),
    ("How should I structure a REST API for a booking system?", True),
    # Simple lookups and chit-chat: should not
    ("What's the capital of Texas?", False),
    ("Thanks, that was great!", False),
    # Tool-answerable: must not plan, or the tool gets bypassed
    ("What's 12% of 340?", False),
    ("What's happening in Houston this weekend?", False),
    ("How do groups work?", False),
]


async def main() -> int:
    agent = create_intent_agent(MODEL, os.getenv("OPENAI_API_KEY"))
    probes = [(sys.argv[1], True)] if len(sys.argv) > 1 else PROBES

    print(f"model={MODEL}\n")
    print(f"{'':4} {'planning':>8} {'expect':>7} {'intent':>13}  {'tool':<22} query")
    print("-" * 110)

    failures = 0
    for query, expected in probes:
        result = (await agent.run(query)).output
        actual = result.requires_planning
        if actual != expected:
            failures += 1
        print(
            f"{'OK ' if actual == expected else 'FAIL':4} "
            f"{str(actual):>8} {str(expected):>7} {result.intent_type:>13}  "
            f"{str(result.suggested_tool):<22} {query}"
        )

    print("-" * 110)
    print("ALL PASS" if not failures else f"{failures} FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
