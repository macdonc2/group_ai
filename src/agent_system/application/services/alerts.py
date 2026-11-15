"""Is the agent itself in trouble? Checks over the recent turn records.

`/health/ready` says the process and the database are up. It cannot say that every chat is
failing, that the model account has run out of credits, or that spend has run away, because
those all happen with the API answering 200. Every turn is already stored (`turn_traces`) with
its outcome, latency, tokens and cost, so these checks read that table; they need no metrics
service.

Each check is written for a single-user app, where an hour may hold a handful of turns:
a share alone would fire on one bad turn out of one, so every check also needs a minimum
count. `evaluate` is pure so the rules are unit-tested without a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

FAILED_OUTCOMES = ("error", "timeout", "step_limit")


@dataclass(frozen=True)
class TurnStat:
    """What the checks need from one stored turn."""

    total_ms: float | None
    input_tokens: int
    cost_usd: float | None
    error: str | None           # None, or how the turn ended badly (error, timeout, step_limit, an exception name)


@dataclass(frozen=True)
class Thresholds:
    window_minutes: int = 60
    failed_turns_min: int = 3           # at least this many failed turns in the window ...
    failed_share: float = 0.3           # ... and at least this share of all turns
    dead_turns_min: int = 2             # turns that used no model tokens at all
    dead_share: float = 0.5
    slow_turns_min: int = 3
    p95_ms: float = 120_000
    spend_hour_usd: float = 5.0
    spend_day_usd: float = 20.0


@dataclass(frozen=True)
class Alert:
    code: str
    summary: str                         # safe to show publicly: no amounts, no user data
    detail: dict[str, Any] = field(default_factory=dict)   # the numbers, for the log only


# What each code means and where to look, in words that are safe on a public endpoint.
SUMMARIES = {
    "model_unreachable": "Chat turns are completing without any model tokens. Check the model API key and the account's credits.",
    "turn_failures": "A large share of recent chat turns ended in an error, a timeout or the step limit. Check the backend log.",
    "slow_turns": "Recent chat turns are far slower than normal. Check model latency and the databases.",
    "spend_hour": "Model spend in the last hour is over budget. Look for a runaway loop or unusual traffic.",
    "spend_day": "Model spend in the last 24 hours is over budget.",
}


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]


DEFAULTS = Thresholds()


def evaluate(turns: list[TurnStat], spend_day_usd: float, t: Thresholds = DEFAULTS) -> list[Alert]:
    """Alerts for one window of turns, plus the last 24 hours' spend."""
    alerts: list[Alert] = []
    n = len(turns)

    # A turn with no input tokens made no successful model call: the key is bad or the credits
    # are gone. It is reported on its own, and not also as a failure, because the fix is different.
    dead = [x for x in turns if x.input_tokens == 0]
    if len(dead) >= t.dead_turns_min and len(dead) / n >= t.dead_share:
        alerts.append(Alert("model_unreachable", SUMMARIES["model_unreachable"], {"dead_turns": len(dead), "turns": n}))

    failed = [x for x in turns if x.error and x.input_tokens > 0]
    if len(failed) >= t.failed_turns_min and len(failed) / n >= t.failed_share:
        outcomes: dict[str, int] = {}
        for x in failed:
            key = x.error if x.error in FAILED_OUTCOMES else "error"
            outcomes[key] = outcomes.get(key, 0) + 1
        alerts.append(Alert("turn_failures", SUMMARIES["turn_failures"],
                            {"failed_turns": len(failed), "turns": n, "outcomes": outcomes}))

    durations = [x.total_ms for x in turns if x.total_ms is not None and not x.error]
    p95 = _p95(durations)
    if len(durations) >= t.slow_turns_min and p95 is not None and p95 > t.p95_ms:
        alerts.append(Alert("slow_turns", SUMMARIES["slow_turns"], {"p95_ms": round(p95), "limit_ms": t.p95_ms, "turns": len(durations)}))

    spend_hour = sum(x.cost_usd or 0.0 for x in turns)
    if t.spend_hour_usd and spend_hour > t.spend_hour_usd:
        alerts.append(Alert("spend_hour", SUMMARIES["spend_hour"], {"spent_usd": round(spend_hour, 2), "limit_usd": t.spend_hour_usd}))
    if t.spend_day_usd and spend_day_usd > t.spend_day_usd:
        alerts.append(Alert("spend_day", SUMMARIES["spend_day"], {"spent_usd": round(spend_day_usd, 2), "limit_usd": t.spend_day_usd}))
    return alerts


async def load_and_evaluate(session: Any, t: Thresholds = DEFAULTS, now: datetime | None = None) -> tuple[list[Alert], int]:
    """Read the window from `turn_traces` and evaluate it. Returns (alerts, turns in the window)."""
    from sqlalchemy import func, select

    from agent_system.adapters.outbound.persistence import TurnTraceModel

    now = now or datetime.utcnow()
    rows = (await session.execute(
        select(TurnTraceModel.total_ms, TurnTraceModel.input_tokens, TurnTraceModel.cost_usd, TurnTraceModel.trace)
        .where(TurnTraceModel.created_at >= now - timedelta(minutes=t.window_minutes))
        .order_by(TurnTraceModel.created_at.desc()).limit(500)
    )).all()
    turns = [TurnStat(total_ms=ms, input_tokens=tokens or 0, cost_usd=cost, error=(trace or {}).get("error"))
             for ms, tokens, cost, trace in rows]
    spend_day = (await session.execute(
        select(func.coalesce(func.sum(TurnTraceModel.cost_usd), 0.0))
        .where(TurnTraceModel.created_at >= now - timedelta(hours=24))
    )).scalar_one()
    return evaluate(turns, float(spend_day or 0.0), t), len(turns)
