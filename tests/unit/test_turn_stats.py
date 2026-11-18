"""The query that feeds the alert checks, and saving a trace with no request session."""

from datetime import datetime, timedelta

import pytest

from agent_system.adapters.outbound.persistence.eval_models import TurnTraceModel
from agent_system.adapters.outbound.persistence.trace_repository import (
    load_turn_stats,
    save_turn_trace,
)

NOW = datetime(2026, 11, 18, 12, 0)


def _row(n: int, minutes_ago: int, cost: float, error: str | None = None) -> TurnTraceModel:
    return TurnTraceModel(id=f"t{n}", user_id="u", conversation_id="c", total_ms=1000.0 * n, input_tokens=10 * n,
                          cost_usd=cost, trace={"error": error} if error else {},
                          created_at=NOW - timedelta(minutes=minutes_ago))


@pytest.mark.unit
async def test_load_turn_stats_returns_the_window_and_the_days_spend(async_session):
    async_session.add_all([_row(1, 5, 0.10), _row(2, 30, 0.20, "timeout"), _row(3, 90, 0.40), _row(4, 60 * 30, 5.0)])
    await async_session.flush()

    turns, spend_day = await load_turn_stats(async_session, window_minutes=60, now=NOW)

    assert [(t.total_ms, t.input_tokens, t.error) for t in turns] == [(1000.0, 10, None), (2000.0, 20, "timeout")]
    assert spend_day == pytest.approx(0.70)  # the 90-minute-old turn counts; the 30-hour-old one does not


@pytest.mark.unit
async def test_save_turn_trace_without_a_session_or_database_reports_nothing_saved():
    class _Trace:
        user_input = "hi"

        def to_dict(self):
            return {"usage": {"input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}, "path": [], "total_ms": 1.0}

    assert await save_turn_trace(_Trace(), user_id="u", conversation_id="c") is None
