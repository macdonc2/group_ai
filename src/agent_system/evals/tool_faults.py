"""Making tools fail on purpose, to see what the agent does about it.

The other suites run with every tool working. In production they do not: web search is
rate-limited, sites refuse page reads, a service is down. What matters then is whether the
agent says so, or papers over it: invents an answer, or reports a failed calendar read as an
empty calendar.

A case lists `tool_faults`. While it runs, a matching tool call does not reach the tool; it
gets the failure instead. Both chat engines call tools through `tools.run_tool`, so one
interceptor covers the state machine and the loop.

Kinds, and what each one tests:

- `error`: the tool returns its own failure result (`success=False` with a message), which is
  what the tools do when they catch a problem such as an HTTP 429. Tests what the agent tells
  the user.
- `exception`: the tool raises. Tests that an unhandled crash in a tool does not crash the turn.
- `timeout`: the tool raises `TimeoutError`. Same, for the timeout path.
- `empty`: the tool succeeds with nothing. Tests that "no results" is not turned into an answer.

`times: N` fails only the first N calls and lets later ones through, for retry behaviour.
Without it every call fails.

A fault only tests something if the agent actually called the tool, so `score_faults` fails a
case whose fault never fired rather than letting it pass for the wrong reason.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

DEFAULT_MESSAGES = {
    "error": "Request failed: 429 Too Many Requests (rate limited). Try again later.",
    "exception": "connection reset by peer",
    "timeout": "timed out after 30 seconds",
    "empty": "No results found.",
}


class ToolFault(BaseModel):
    tool: str                                              # name in the tool registry, e.g. web_search
    kind: Literal["error", "exception", "timeout", "empty"] = "error"
    message: str | None = None                             # what the failure says; a realistic default otherwise
    times: int | None = None                               # fail the first N calls only; None = every call
    required: bool = True                                  # the case fails if this fault never fired; set false for
                                                           # a tool the agent may reasonably use instead of another


@dataclass
class FaultPlan:
    """The faults for one running case, with counts of what happened."""

    faults: list[ToolFault]
    calls: dict[str, int] = field(default_factory=dict)    # tool -> calls seen
    fired: dict[str, int] = field(default_factory=dict)    # tool -> calls that got a fault

    def next_fault(self, tool: str) -> ToolFault | None:
        self.calls[tool] = self.calls.get(tool, 0) + 1
        for fault in self.faults:
            if fault.tool == tool and (fault.times is None or self.fired.get(tool, 0) < fault.times):
                self.fired[tool] = self.fired.get(tool, 0) + 1
                return fault
        return None

    def report(self) -> dict[str, Any]:
        planned = sorted({f.tool for f in self.faults})
        required = sorted({f.tool for f in self.faults if f.required})
        # with only optional faults, at least one of them must still have fired
        missed = [t for t in required if not self.fired.get(t)]
        if not required and not any(self.fired.values()):
            missed = planned
        return {"planned": planned, "calls": dict(self.calls), "fired": dict(self.fired), "never_reached": missed}


_plan: contextvars.ContextVar[FaultPlan | None] = contextvars.ContextVar("eval_tool_faults", default=None)
_installed = False


def set_faults(faults: list[ToolFault] | None) -> tuple[FaultPlan | None, contextvars.Token]:
    plan = FaultPlan(list(faults)) if faults else None
    return plan, _plan.set(plan)


def reset_faults(token: contextvars.Token) -> None:
    _plan.reset(token)


async def intercept(name: str, kwargs: dict[str, Any]) -> Any:
    """Called by `tools.run_tool` before every tool. Returns a result to use instead of calling the
    tool, raises to simulate a crash, or returns None to let the real tool run."""
    plan = _plan.get()
    fault = plan.next_fault(name) if plan is not None else None
    if fault is None:
        return None
    from agent_system.adapters.outbound.llm.tools import ToolResult

    message = fault.message or DEFAULT_MESSAGES[fault.kind]
    if fault.kind == "exception":
        raise RuntimeError(message)
    if fault.kind == "timeout":
        raise TimeoutError(message)
    if fault.kind == "empty":
        return ToolResult(success=True, data=[], message=message)
    return ToolResult(success=False, data=None, message=message)


def install_tool_fault_hook() -> None:
    """Register the interceptor once. It does nothing for cases without `tool_faults`."""
    global _installed
    if _installed:
        return
    from agent_system.adapters.outbound.llm import tools

    tools.set_tool_interceptor(intercept)
    _installed = True
