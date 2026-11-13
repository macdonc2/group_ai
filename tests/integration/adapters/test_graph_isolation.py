"""One user's memory must never be returned to another (real Neo4j, two users).

Both users use the same tool, so their graphs are joined through the shared
tool node; and conversation summaries were historically stored with no owner.
Those are the two ways data crossed between users.
"""

import pytest

from agent_system.adapters.outbound.graph.neo4j_adapter import Neo4jAdapter
from agent_system.domain.value_objects import UserId

pytestmark = pytest.mark.integration

ALICE = UserId.from_string("11111111-1111-1111-1111-111111111111")
BOB = UserId.from_string("22222222-2222-2222-2222-222222222222")
ALICE_SECRET = "Alice asked about her dog Zane's kidney medication"
BOB_SECRET = "Bob asked about his dog Rex's training class"


@pytest.fixture(scope="module")
def neo4j_url():
    from testcontainers.neo4j import Neo4jContainer

    with Neo4jContainer("neo4j:5") as neo:
        yield neo.get_connection_url(), neo.username, neo.password


@pytest.fixture
async def graph(neo4j_url):
    uri, user, password = neo4j_url
    adapter = Neo4jAdapter(uri, user, password)
    await adapter.connect()
    async with adapter.driver.session() as session:
        await session.run("MATCH (n) DETACH DELETE n")
    for owner, summary, entity in ((ALICE, ALICE_SECRET, "Zane"), (BOB, BOB_SECRET, "Rex")):
        await adapter.record_interaction(
            user_id=owner, conversation_id=f"conv-{entity}", summary=summary,
            intents=["pet care"], entities=[entity, "dog"], tools_used=["web_search"],
        )
    await adapter.record_group_interaction(
        group_id="group-1", user_id=str(ALICE), conversation_id="conv-group",
        summary="dog park meetup on Saturday", topics=["dog park"], entities=[],
    )
    yield adapter
    await adapter.close()


def _text(rows) -> str:
    return " | ".join(str(r["content"]) for r in rows)


async def test_topic_recall_returns_only_the_callers_memory(graph):
    bob = _text(await graph.recall_about_topic(BOB, "dog", limit=20))
    assert "Rex" in bob
    assert "Zane" not in bob and "Alice" not in bob

    alice = _text(await graph.recall_about_topic(ALICE, "dog", limit=20))
    assert "Zane" in alice
    assert "Rex" not in alice and "Bob" not in alice


async def test_topic_recall_cannot_search_for_another_users_entity(graph):
    assert await graph.recall_about_topic(BOB, "Zane", limit=20) == []


async def test_private_recall_does_not_return_group_conversations(graph):
    assert "meetup" not in _text(await graph.recall_about_topic(BOB, "dog", limit=20))


async def test_user_nodes_stop_at_the_shared_tool_node(graph):
    labels = {n.label for n in await graph.get_user_nodes(BOB)}
    assert BOB_SECRET in labels and "Rex" in labels
    assert ALICE_SECRET not in labels and "Zane" not in labels

    labels = {n.label for n in await graph.get_user_nodes(ALICE)}
    assert ALICE_SECRET in labels
    assert BOB_SECRET not in labels and "Rex" not in labels


async def test_new_conversation_summaries_carry_their_owner(graph):
    async with graph.driver.session() as session:
        result = await session.run(
            "MATCH (n:KnowledgeNode {node_type: 'interaction'}) WHERE n.label IN $labels RETURN n.label AS label, n.user_id AS owner",
            labels=[ALICE_SECRET, BOB_SECRET],
        )
        owners = {r["label"]: r["owner"] async for r in result}
    assert owners == {ALICE_SECRET: str(ALICE), BOB_SECRET: str(BOB)}
