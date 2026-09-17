"""'What do you know about my wife and pets?' must surface the stored people and pets."""

import pytest

from agent_system.adapters.outbound.llm import tools as tools_mod

USER = "11111111-1111-1111-1111-111111111111"

PEOPLE = [
    {"name": "Rachel", "relationship_type": "spouse", "context_notes": "Loves tacos and hates cilantro", "aliases": ["Rach"], "mention_count": 12},
    {"name": "Zane", "relationship_type": "friend", "context_notes": "Lives in Montrose", "aliases": [], "mention_count": 8},
    {"name": "Mark", "relationship_type": "colleague", "context_notes": "", "aliases": [], "mention_count": 2},
]
PETS = [
    {"name": "Roxanne", "species": "dog", "breed": "boxer", "personality": ["goofy", "food-motivated"], "food_preferences": ["ham bones"], "health_notes": ""},
    {"name": "George", "species": "cat", "breed": "", "personality": ["bitey"], "food_preferences": [], "health_notes": "soft bites when overstimulated"},
    {"name": "Bo", "species": "cat", "breed": "", "personality": [], "food_preferences": [], "health_notes": ""},
]


class FakeKG:
    def __init__(self):
        self.calls = []

    async def list_known_people(self, user_id, relationship_type=None, limit=50):
        self.calls.append(("people", relationship_type))
        return [p for p in PEOPLE if not relationship_type or p["relationship_type"] == relationship_type]

    async def list_pets(self, user_id, species=None):
        self.calls.append(("pets", species))
        return [p for p in PETS if not species or p["species"] == species]

    async def get_person(self, user_id, name):
        return next((p for p in PEOPLE if p["name"].lower() == name.lower()), None)

    async def get_pet(self, user_id, name):
        return next((p for p in PETS if p["name"].lower() == name.lower()), None)

    async def recall_about_topic(self, user_id, topic, limit=5):
        return [{"content": "What do you know about my cats?", "role": "user", "source_type": "message"}]

    async def get_user_nodes(self, user_id, node_type=None):
        return []


@pytest.mark.unit
async def test_wife_and_pets_returns_names(monkeypatch):
    kg = FakeKG()
    r = await tools_mod.recall_about_topic("wife and pets", USER, kg, embedding_port=None)
    assert r.success
    msg = r.message
    assert "**Rachel** — your spouse" in msg and "Loves tacos" in msg
    assert "**Roxanne** — your dog (boxer)" in msg and "**George** — your cat" in msg and "**Bo**" in msg
    assert "Zane" not in msg and "Mark" not in msg  # not the wife, not a pet
    # past questions are labelled as questions, not as facts
    assert "not stored facts" in msg or "Related past messages" not in msg


@pytest.mark.unit
async def test_species_and_name_matching():
    kg = FakeKG()
    r = await tools_mod.recall_about_topic("my cats", USER, kg)
    assert "George" in r.message and "Bo" in r.message and "Roxanne" not in r.message
    r = await tools_mod.recall_about_topic("Rach", USER, kg)  # alias
    assert "Rachel" in r.message
    r = await tools_mod.recall_about_topic("family", USER, kg)
    assert "Rachel" in r.message and "Zane" not in r.message
    r = await tools_mod.recall_about_topic("friends", USER, kg)
    assert "Zane" in r.message and "Rachel" not in r.message


@pytest.mark.unit
async def test_named_pet_still_gets_profile():
    kg = FakeKG()
    r = await tools_mod.recall_about_topic("Roxanne", USER, kg)
    assert "Roxanne is the user's dog" in r.message and "boxer" in r.message


@pytest.mark.unit
async def test_summary_includes_people_and_pets():
    kg = FakeKG()

    class Node:
        def __init__(self, t, label):
            self.node_type = type("T", (), {"value": t})()
            self.label = label
            self.properties = {}
            self.created_at = None

    async def nodes(user_id, node_type=None):
        return [Node("topic", "cycling"), Node("interaction", "asked about pets")]

    kg.get_user_nodes = nodes
    r = await tools_mod.summarize_user_knowledge(USER, kg)
    assert r.success
    assert "People in your life (3)" in r.message and "Rachel" in r.message and "Mark" in r.message
    assert "Your pets (3)" in r.message and "Roxanne" in r.message
    assert "Topics of Interest" in r.message


@pytest.mark.unit
async def test_no_graph_is_graceful():
    r = await tools_mod.recall_about_topic("wife", USER, None)
    assert r.success and "hasn't been discussed" in r.message
