"""The router gets only the user's own statements from other conversations."""

from types import SimpleNamespace

import pytest

from agent_system.adapters.outbound.fsm.nodes import _intent_memory_hints

pytestmark = pytest.mark.unit


class FakeKG:
    async def semantic_search(self, user_id, query_embedding, limit, min_score):
        return [
            {"role": "assistant", "conversation_id": "old", "content": "I don't have live internet access", "score": 0.9},
            {"role": "user", "conversation_id": "old", "content": "What patents am I on?", "score": 0.99},
            {"role": "user", "conversation_id": "now", "content": "said in this chat", "score": 0.95},
            {"role": "user", "conversation_id": "old2", "content": "What patents am I on brother?", "score": 0.93},
            {"role": "user", "conversation_id": "old3", "content": "what patents am i on brother", "score": 0.93},
            {"role": "user", "conversation_id": "old", "content": "For patent searches use my name: Cody J MacDonald", "score": 0.77},
            {"role": "user", "conversation_id": "old", "content": "For patent searches use my name: Cody J MacDonald", "score": 0.77},
            {"role": "user", "conversation_id": "old", "content": "patent is here: https://patents.google.com/patent/US1", "score": 0.75},
        ]


class FakeEmbedder:
    async def embed(self, text):
        return SimpleNamespace(embedding=[0.1, 0.2])


async def test_only_other_conversations_user_statements_reach_the_router():
    recorded = []
    deps = SimpleNamespace(knowledge_graph_port=FakeKG(), embedding_port=FakeEmbedder(),
                           record_retrieval=lambda *a, **k: recorded.append(a))
    state = SimpleNamespace(user_input="Hey brother, what are my patents?", input_embedding=None,
                            user=SimpleNamespace(id="u"), conversation=SimpleNamespace(id="now"))
    hints = await _intent_memory_hints(SimpleNamespace(deps=deps, state=state))
    # repeated past questions don't crowd out the instruction; duplicates collapse
    assert hints == ["For patent searches use my name: Cody J MacDonald", "patent is here: https://patents.google.com/patent/US1"]
    assert state.input_embedding == [0.1, 0.2]  # cached for GenerateResponse
    assert recorded and recorded[0][0] == "intent_memory"


async def test_no_memory_backends_means_no_hints():
    deps = SimpleNamespace(knowledge_graph_port=None, embedding_port=None)
    assert await _intent_memory_hints(SimpleNamespace(deps=deps, state=SimpleNamespace())) == []
