"""Real conversations as eval subjects.

Turns are rebuilt from stored messages (user message → following assistant
reply); the TurnTrace recorded for a turn is attached when one exists
(conversations from before tracing have transcripts only). There is no ground
truth, so these are judged with rubrics only.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from agent_system.adapters.outbound.persistence import (
    ConversationModel,
    MessageModel,
    TurnTraceModel,
)


async def list_user_conversations(session: Any, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
    convs = (await session.execute(
        select(ConversationModel)
        .where(ConversationModel.user_id == user_id)
        .order_by(ConversationModel.updated_at.desc())
        .limit(limit)
    )).scalars().all()
    if not convs:
        return []
    ids = [c.id for c in convs]
    msg_counts = dict((await session.execute(
        select(MessageModel.conversation_id, func.count()).where(MessageModel.conversation_id.in_(ids))
        .group_by(MessageModel.conversation_id)
    )).all())
    traced = dict((await session.execute(
        select(TurnTraceModel.conversation_id, func.count()).where(TurnTraceModel.conversation_id.in_(ids))
        .group_by(TurnTraceModel.conversation_id)
    )).all())
    return [{
        "conversation_id": c.id,
        "title": c.title,
        "messages": msg_counts.get(c.id, 0),
        "traced_turns": traced.get(c.id, 0),
        "last_at": (c.updated_at or c.created_at).isoformat(),
    } for c in convs if msg_counts.get(c.id, 0) > 0]


async def load_conversation(session: Any, conversation_id: str, user_id: str) -> tuple[str, list[dict[str, Any]]] | None:
    """(title, turns) for one of the user's conversations, or None if it isn't theirs."""
    conv = await session.get(ConversationModel, conversation_id)
    if conv is None or conv.user_id != user_id:
        return None
    messages = (await session.execute(
        select(MessageModel).where(MessageModel.conversation_id == conversation_id).order_by(MessageModel.created_at)
    )).scalars().all()
    traces = (await session.execute(
        select(TurnTraceModel).where(TurnTraceModel.conversation_id == conversation_id)
        .order_by(TurnTraceModel.created_at)
    )).scalars().all()
    unmatched = list(traces)

    turns: list[dict[str, Any]] = []
    pending: MessageModel | None = None
    for m in messages:
        if m.role == "user":
            if pending is not None:
                turns.append(_turn(pending, None, unmatched))
            pending = m
        elif m.role == "assistant" and pending is not None:
            turns.append(_turn(pending, m, unmatched))
            pending = None
    if pending is not None:
        turns.append(_turn(pending, None, unmatched))
    return (conv.title or conversation_id), turns


def _turn(user_msg: Any, reply: Any, unmatched: list[Any]) -> dict[str, Any]:
    trace = next((t for t in unmatched if (t.user_input or "").strip() == (user_msg.content or "").strip()[:4000]), None)
    if trace is not None:
        unmatched.remove(trace)
    return {
        "user": user_msg.content,
        "response": reply.content if reply is not None else "",
        "trace": trace.trace if trace is not None else None,
        "tool_calls": (reply.tool_calls or []) if reply is not None else [],
        "at": user_msg.created_at.isoformat() if user_msg.created_at else None,
    }
