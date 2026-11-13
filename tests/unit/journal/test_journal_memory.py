"""Journal entries into memory: chunking, labelling, ownership, and surviving partial failure.

A recording stand-in replaces the graph and the extractors, so nothing here touches a
model, a database or the network.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from agent_system.adapters.outbound.llm import journal_memory as jm

pytestmark = pytest.mark.unit

ALICE = "11111111-1111-1111-1111-111111111111"


class RecordingGraph:
    def __init__(self, fail: str | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.fail = fail

    def __getattr__(self, name):
        async def call(*args, **kwargs):
            if args:  # delete_conversation_memory / list_* are called positionally
                kwargs = {"args": args, **kwargs}
            self.calls.append((name, kwargs))
            if name == self.fail:
                raise RuntimeError("boom")
            return [] if name.startswith("list_") else 0

        return call

    def named(self, name: str) -> list[dict]:
        return [kwargs for called, kwargs in self.calls if called == name]


class FakeEmbedder:
    async def embed(self, text):
        return SimpleNamespace(embedding=[0.1, 0.2, 0.3])


def _found(**kinds):
    empty = {"persons": [], "pets": [], "locations": [], "preferences": [], "relationships": []}
    return SimpleNamespace(**{**empty, **kinds})


async def _remember(graph, body="Walked Zane with Sam.", *, embedder=FakeEmbedder(), found=None, topics=("Sam",)):
    async def topics_fn(text):
        return list(topics)

    async def entities_fn(text, **kwargs):
        return found or _found()

    return await jm.remember_entry(
        kg=graph, embedder=embedder, user_id=ALICE, user_label="alice@example.com", entry_id="e1",
        entry_date="2026-11-13", body=body, topics_fn=topics_fn, entities_fn=entities_fn,
    )


def test_short_entries_are_one_chunk_and_long_ones_split_on_paragraphs():
    assert jm.split_into_chunks("One thought.\n\nAnother.") == ["One thought.\n\nAnother."]

    paragraphs = [f"Paragraph {i} " + "x" * 600 for i in range(5)]
    chunks = jm.split_into_chunks("\n\n".join(paragraphs))
    assert len(chunks) == 3 and all(len(c) <= jm.CHUNK_CHARS for c in chunks)
    assert "".join(chunks).count("Paragraph") == 5  # nothing lost, no paragraph cut in half

    assert all(len(c) <= jm.CHUNK_CHARS for c in jm.split_into_chunks("y" * 4000))  # one huge paragraph
    assert len(jm.split_into_chunks("z" * 100_000)) == jm.MAX_CHUNKS


def test_stored_text_says_it_is_a_journal_entry_and_from_which_day():
    assert jm.embedded_text("2026-11-13", "Walked Zane.") == "[Journal entry, Friday, November 13, 2026]\nWalked Zane."


async def test_everything_written_is_stamped_with_the_owner_and_filed_under_the_entry():
    graph = RecordingGraph()
    found = _found(
        persons=[SimpleNamespace(name="Sam", aliases=[], relationship_type="friend", context_notes=None, confidence=0.9),
                 SimpleNamespace(name="Maybe", aliases=[], relationship_type=None, context_notes=None, confidence=0.3)],
    )

    assert await _remember(graph, found=found) == "done"

    owner_calls = [(name, kwargs) for name, kwargs in graph.calls if "user_id" in kwargs]
    assert {name for name, _ in owner_calls} == {"store_message_embedding", "record_interaction", "store_person"}
    assert all(str(kwargs["user_id"]) == ALICE for _, kwargs in owner_calls)

    [embedding] = graph.named("store_message_embedding")
    assert embedding["conversation_id"] == "journal:e1" and embedding["role"] == "user"
    assert embedding["content"].startswith("[Journal entry, Friday, November 13, 2026]")
    assert embedding["metadata"]["source"] == "journal" and embedding["metadata"]["entry_date"] == "2026-11-13"
    [summary] = graph.named("record_interaction")
    assert summary["conversation_id"] == "journal:e1" and summary["entities"] == ["Sam"]
    assert [p["name"] for p in graph.named("store_person")] == ["Sam"]  # the low-confidence guess is dropped


async def test_an_edit_clears_the_old_memory_before_writing_the_new():
    graph = RecordingGraph()
    await _remember(graph)
    first = graph.calls[0]
    assert first[0] == "delete_conversation_memory"
    assert str(first[1]["args"][0]) == ALICE and first[1]["args"][1] == "journal:e1"


async def test_a_failed_extraction_still_leaves_the_entry_searchable():
    graph = RecordingGraph(fail="list_known_people")
    assert await _remember(graph) == "failed"  # reported, so the UI can offer a retry
    assert len(graph.named("store_message_embedding")) == 1
    assert len(graph.named("record_interaction")) == 1


async def test_without_a_graph_nothing_is_attempted():
    assert await _remember(None) == "skipped"
    assert await jm.forget_entry(None, ALICE, "e1") == 0


def test_only_recent_entries_are_checked_for_future_plans():
    today = datetime.now(ZoneInfo("America/Chicago")).date()
    assert jm.worth_suggesting(today.isoformat(), "America/Chicago")
    assert jm.worth_suggesting((today - timedelta(days=1)).isoformat(), "America/Chicago")
    assert not jm.worth_suggesting((today - timedelta(days=30)).isoformat(), "America/Chicago")
    assert not jm.worth_suggesting("not-a-date", "America/Chicago")
    assert jm.worth_suggesting(datetime.utcnow().date().isoformat(), "Not/AZone")  # falls back to UTC
