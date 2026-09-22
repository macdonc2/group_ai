"""Persist and query TurnTraces from real traffic."""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from agent_system.adapters.outbound.persistence.eval_models import TurnTraceModel

logger = logging.getLogger(__name__)


def trace_token_count(trace: Any) -> int:
    """Total LLM tokens of a turn (for messages.token_count / conversations.total_tokens_used)."""
    if trace is None:
        return 0
    usage = trace.usage("system")
    return int(usage["input_tokens"] + usage["output_tokens"])


async def save_turn_trace(
    trace: Any,
    *,
    user_id: str,
    conversation_id: str,
    message_id: str | None = None,
    source: str = "chat",
    session: Any = None,
) -> str | None:
    """Persist one turn trace; never raises.

    Pass the request's `session` to write in the same transaction as the turn's
    messages (required on SQLite, whose single writer lock that session holds).
    Without one, a short-lived session of its own is used.
    """
    if trace is None:
        return None
    try:
        from agent_system.adapters.inbound.api.dependencies import get_database

        data = trace.to_dict()
        usage = data["usage"]
        row = TurnTraceModel(
            id=str(uuid.uuid4()),
            user_id=str(user_id),
            conversation_id=str(conversation_id),
            message_id=message_id,
            source=source,
            user_input=(trace.user_input or "")[:4000],
            path=data["path"],
            trace=data,
            total_ms=data["total_ms"],
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            cost_usd=usage["cost_usd"],
        )
        if session is not None:
            async with session.begin_nested():  # a savepoint, so a bad row can't poison the turn
                session.add(row)
            return row.id
        async with get_database().session() as own:
            own.add(row)
            await own.commit()
        return row.id
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to persist turn trace: %s", exc)
        return None


async def mark_orphaned_eval_runs(database: Any) -> int:
    """API-started eval runs execute in-process, so any still 'running' at startup died with
    the last process. CLI runs may be live elsewhere; they're only swept once clearly stale."""
    from agent_system.adapters.outbound.persistence.eval_models import EvalRunModel

    stale_before = datetime.utcnow() - timedelta(hours=12)
    async with database.session() as session:
        rows = (await session.execute(select(EvalRunModel).where(EvalRunModel.status == "running"))).scalars()
        n = 0
        for run in rows:
            if (run.config or {}).get("origin") == "api" or run.started_at < stale_before:
                run.status, run.completed_at = "interrupted", datetime.utcnow()
                run.error = "The process running this eval stopped before it finished"
                n += 1
        await session.commit()
        return n


class TurnTraceRepository:
    def __init__(self, session: Any) -> None:
        self._session = session

    async def list_for_conversation(self, conversation_id: str, user_id: str | None = None) -> list[TurnTraceModel]:
        stmt = select(TurnTraceModel).where(TurnTraceModel.conversation_id == conversation_id)
        if user_id is not None:
            stmt = stmt.where(TurnTraceModel.user_id == user_id)
        result = await self._session.execute(stmt.order_by(TurnTraceModel.created_at))
        return list(result.scalars())

    async def recent(self, since_days: int = 7, limit: int = 200, user_id: str | None = None) -> list[TurnTraceModel]:
        stmt = select(TurnTraceModel).where(
            TurnTraceModel.created_at >= datetime.utcnow() - timedelta(days=since_days)
        )
        if user_id is not None:
            stmt = stmt.where(TurnTraceModel.user_id == user_id)
        result = await self._session.execute(stmt.order_by(TurnTraceModel.created_at.desc()).limit(limit))
        return list(result.scalars())
