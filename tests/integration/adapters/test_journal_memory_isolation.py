"""Journal memory in a real Neo4j: owned by its writer, replaceable, removable (two users).

Both users journal about a dog and both mention a person called Sam, so anything
matched by name or keyword without an owner filter would cross between them.
"""

from types import SimpleNamespace

import pytest

from agent_system.adapters.outbound.graph.neo4j_adapter import Neo4jAdapter
from agent_system.adapters.outbound.llm import journal_memory as jm
from agent_system.domain.value_objects import UserId

pytestmark = pytest.mark.integration

ALICE = "11111111-1111-1111-1111-111111111111"
BOB = "22222222-2222-2222-2222-222222222222"
ALICE_ENTRY = "Sam came with me to the vet. Zane's kidney results were bad and I cried in the car."
BOB_ENTRY = "Sam and I took Rex to the dog training class. Rex finally sat on command."


class FakeEmbedder:
    """Deterministic vectors; both users' entries get the same one, so only ownership separates them."""

    async def embed(self, text):
        return SimpleNamespace(embedding=[1.0, 0.0, 0.0])


def _person(name):
    return SimpleNamespace(name=name, aliases=[], relationship_type="friend", context_notes=None, confidence=0.9)


def _pet(name):
    return SimpleNamespace(name=name, aliases=[], species="dog", breed=None, traits=None, food_preferences=None,
                           confidence=0.9)


async def _remember(graph, user_id, entry_id, body, pet):
    async def topics_fn(text):
        return [pet, "dog"]

    async def entities_fn(text, **kwargs):
        return SimpleNamespace(persons=[_person("Sam")], pets=[_pet(pet)], locations=[], preferences=[],
                               relationships=[])

    return await jm.remember_entry(
        kg=graph, embedder=FakeEmbedder(), user_id=user_id, user_label=None, entry_id=entry_id,
        entry_date="2026-11-13", body=body, topics_fn=topics_fn, entities_fn=entities_fn,
    )


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
    assert await _remember(adapter, ALICE, "entry-a", ALICE_ENTRY, "Zane") == "done"
    assert await _remember(adapter, BOB, "entry-b", BOB_ENTRY, "Rex") == "done"
    yield adapter
    await adapter.close()


def _text(rows) -> str:
    return " | ".join(str(r["content"]) for r in rows)


async def _count(graph, query, **params) -> int:
    async with graph.driver.session() as session:
        record = await (await session.run(query, **params)).single()
    return record["n"]


async def test_a_journal_entry_can_be_recalled_by_its_writer_with_its_date(graph):
    alice = _text(await graph.recall_about_topic(UserId.from_string(ALICE), "vet", limit=20))
    assert "kidney results" in alice
    assert "[Journal entry, Friday, November 13, 2026]" in alice


async def test_topic_recall_never_returns_another_users_journal(graph):
    for topic in ("dog", "Sam", "Zane", "kidney", "Journal"):
        bob = _text(await graph.recall_about_topic(UserId.from_string(BOB), topic, limit=50))
        assert "Zane" not in bob and "kidney" not in bob and "vet" not in bob, topic
    alice = _text(await graph.recall_about_topic(UserId.from_string(ALICE), "Sam", limit=50))
    assert "Rex" not in alice and "training class" not in alice


async def test_semantic_search_never_returns_another_users_journal(graph):
    # Identical vectors: the only thing keeping the results apart is the owner filter.
    for search in (graph.semantic_search, graph._brute_force_semantic_search):
        bob = _text(await search(UserId.from_string(BOB), [1.0, 0.0, 0.0], 10, 0.1))
        assert "Rex" in bob and "Zane" not in bob
        alice = _text(await search(UserId.from_string(ALICE), [1.0, 0.0, 0.0], 10, 0.1))
        assert "Zane" in alice and "Rex" not in alice


async def test_people_and_pets_from_a_journal_belong_to_its_writer(graph):
    assert [p["name"] for p in await graph.list_pets(UserId.from_string(BOB))] == ["Rex"]
    assert [p["name"] for p in await graph.list_pets(UserId.from_string(ALICE))] == ["Zane"]
    # Both know a "Sam"; each has their own node rather than sharing one.
    assert await _count(graph, "MATCH (p:PersonNode {name: 'Sam'}) RETURN count(DISTINCT p.user_id) AS n") == 2


async def test_the_graph_view_of_one_user_has_none_of_the_others_journal(graph):
    labels = {n.label for n in await graph.get_user_nodes(UserId.from_string(BOB))}
    assert any("Rex" in label for label in labels)
    assert not any("Zane" in label or "vet" in label for label in labels)


async def test_every_journal_node_carries_its_owner(graph):
    unowned = await _count(
        graph,
        """
        MATCH (n) WHERE (n:MessageEmbedding AND n.conversation_id STARTS WITH 'journal:')
                     OR (n:KnowledgeNode AND n.node_type = 'interaction' AND n.label STARTS WITH 'Journal ')
                     OR n:PersonNode OR n:PetNode
        WITH n WHERE n.user_id IS NULL RETURN count(n) AS n
        """,
    )
    assert unowned == 0


async def test_one_user_cannot_delete_anothers_journal_memory(graph):
    assert await graph.delete_conversation_memory(UserId.from_string(BOB), jm.memory_key("entry-a")) == 0
    assert "kidney" in _text(await graph.recall_about_topic(UserId.from_string(ALICE), "vet", limit=20))


async def test_deleting_an_entry_removes_its_text_and_keeps_the_facts(graph):
    removed = await jm.forget_entry(graph, ALICE, "entry-a")

    assert removed == 2  # one embedding, one summary node
    assert "kidney" not in _text(await graph.recall_about_topic(UserId.from_string(ALICE), "vet", limit=20))
    assert await graph.semantic_search(UserId.from_string(ALICE), [1.0, 0.0, 0.0], 10, 0.1) == []
    assert [p["name"] for p in await graph.list_pets(UserId.from_string(ALICE))] == ["Zane"]  # the fact stays
    # ...and the other user's journal is untouched.
    assert "Rex" in _text(await graph.recall_about_topic(UserId.from_string(BOB), "training", limit=20))


async def test_editing_replaces_the_stored_text_instead_of_adding_to_it(graph):
    await _remember(graph, ALICE, "entry-a", "Rewritten: a quiet day with Zane.", "Zane")

    assert await _count(graph, "MATCH (m:MessageEmbedding {conversation_id: 'journal:entry-a'}) RETURN count(m) AS n") == 1
    alice = _text(await graph.recall_about_topic(UserId.from_string(ALICE), "Zane", limit=20))
    assert "quiet day" in alice and "kidney" not in alice
    assert await _count(
        graph, "MATCH (n:KnowledgeNode {node_type: 'interaction', user_id: $u}) RETURN count(n) AS n", u=ALICE) == 1
