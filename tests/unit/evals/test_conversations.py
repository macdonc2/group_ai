"""Rebuilding real conversations into judgeable turns."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agent_system.adapters.outbound.persistence import (
    Base,
    ConversationModel,
    MessageModel,
    TurnTraceModel,
    UserModel,
)
from agent_system.evals.conversations import list_user_conversations, load_conversation

pytestmark = pytest.mark.unit
T0 = datetime(2026, 9, 1)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)() as s:
        s.add(UserModel(id="u1", email="a@x", hashed_password="!"))
        s.add(ConversationModel(id="c1", user_id="u1", title="Zane"))
        rows = [("user", "Hi"), ("assistant", "Hello!"), ("user", "What's 2+2?"), ("assistant", "4"), ("user", "bye")]
        for i, (role, text) in enumerate(rows):
            s.add(MessageModel(id=f"m{i}", conversation_id="c1", role=role, content=text,
                               tool_calls=[{"tool_name": "calculate"}] if text == "4" else [],
                               created_at=T0 + timedelta(minutes=i)))
        s.add(TurnTraceModel(id="t1", user_id="u1", conversation_id="c1", user_input="What's 2+2?",
                             trace={"path": ["ReceiveInput"]}))
        await s.commit()
        yield s
    await engine.dispose()


async def test_pairs_turns_and_attaches_traces(session):
    title, turns = await load_conversation(session, "c1", "u1")
    assert title == "Zane"
    assert [(t["user"], t["response"]) for t in turns] == [("Hi", "Hello!"), ("What's 2+2?", "4"), ("bye", "")]
    assert turns[0]["trace"] is None and turns[1]["trace"] == {"path": ["ReceiveInput"]}
    assert turns[1]["tool_calls"] == [{"tool_name": "calculate"}]


async def test_other_users_conversations_are_not_loaded(session):
    assert await load_conversation(session, "c1", "someone-else") is None


async def test_listing_counts_traced_turns(session):
    [c] = await list_user_conversations(session, "u1")
    assert c["messages"] == 5 and c["traced_turns"] == 1
