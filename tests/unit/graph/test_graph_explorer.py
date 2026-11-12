"""Graph snapshot operations, the explorer agent's tools/loop, and the graph-QA scorer."""

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from agent_system.adapters.outbound.llm.graph_agent import ask_graph
from agent_system.application.services.graph_explorer import GraphSnapshot, clean_properties
from agent_system.evals.graph_qa import GraphCase, load_graph_suite, score_case

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def snap() -> GraphSnapshot:
    return load_graph_suite().snapshot()


def labels(nodes) -> set[str]:
    return {n.label for n in nodes}


class TestSnapshot:
    def test_drops_dangling_and_duplicate_edges(self):
        s = GraphSnapshot.from_records(
            [{"id": "a", "type": "t", "label": "A"}, {"id": "b", "type": "t", "label": "B"}],
            [{"source": "a", "target": "b", "type": "X"}, {"source": "a", "target": "b", "type": "X"},
             {"source": "a", "target": "ghost", "type": "X"}],
        )
        assert len(s.edges) == 1
        assert s.degree("a") == 1

    def test_handles_round_trip_and_are_stable(self, snap):
        again = load_graph_suite().snapshot()
        for node in snap.nodes:
            handle = snap.handle(node.id)
            assert snap.resolve(handle) is node
            assert again.handle(node.id) == handle
        assert snap.resolve("n999") is None

    def test_counts(self, snap):
        assert snap.node_type_counts()["pet"] == 2
        assert snap.edge_type_counts()["KNOWS"] == 3

    def test_search_ranks_label_over_property(self, snap):
        hits = snap.search("austin")
        assert labels(n for n, _ in hits) == {"Maya Okafor", "Crux Climbing Gym"}
        assert snap.search("maya")[0][0].id == "p-maya"
        assert snap.search("zzz") == []

    def test_search_empty_query_lists_type(self, snap):
        hits = snap.search("", node_types={"pet"})
        assert labels(n for n, _ in hits) == {"Biscuit", "Miso"}

    def test_traverse_depth_and_filters(self, snap):
        one, _ = snap.traverse("p-maya", depth=1)
        assert labels(n for n, _, _ in one) == {"riley@example.com", "Crux Climbing Gym", "rock climbing"}
        places, _ = snap.traverse("u1", depth=2, node_types={"location"})
        assert labels(n for n, _, _ in places) == {"Crux Climbing Gym", "Blue Door Coffee", "Northwind Office"}
        assert {d for n, d, _ in places if n.id == "l-gym"} == {2}
        known, _ = snap.traverse("u1", depth=1, edge_types={"KNOWS"}, direction="out")
        assert len(known) == 3
        assert snap.traverse("u1", depth=1, direction="in")[0] == []

    def test_traverse_reports_truncation(self, snap):
        found, cut = snap.traverse("u1", depth=1, limit=5)
        assert len(found) == 5
        assert cut == snap.degree("u1") - 5

    def test_shortest_path(self, snap):
        assert [h.other for h in snap.connecting_path("p-maya", "t-trip")] == ["t-climb", "t-trip"]
        assert [h.other for h in snap.connecting_path("p-maya", "p-dev")] == ["u1", "p-dev"]  # only route
        assert len(snap.shortest_path("p-maya", "t-trip")) == 2
        assert snap.shortest_path("p-maya", "p-maya") == []
        assert snap.shortest_path("p-maya", "tool-web", max_hops=1) is None
        assert snap.shortest_path("p-june", "l-cafe", edge_types={"KNOWS"}) is None

    def test_clean_properties_hides_internals_and_clips(self):
        out = clean_properties({"user_id": "x", "embedding": [0.1], "note": "a" * 500, "empty": ""})
        assert set(out) == {"note"}
        assert len(out["note"]) < 200


def scripted(*turns):
    """A model that plays back tool calls, then a final structured answer."""
    calls = iter(turns)
    seen_results: list[str] = []

    def run(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        for part in messages[-1].parts:
            if isinstance(part, ToolReturnPart):
                seen_results.append(str(part.content))
        step = next(calls)
        if isinstance(step, tuple):
            return ModelResponse(parts=[ToolCallPart(step[0], step[1])])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, step)])

    return FunctionModel(run), seen_results


class TestAgent:
    async def test_tools_answer_and_highlight_validation(self, snap):
        maya = snap.handle("p-maya")
        model, results = scripted(
            ("search_nodes", {"query": "Maya"}),
            ("get_node", {"node": maya}),
            {"answer": "Maya Okafor is your sibling.", "highlight": [maya, "n999"],
             "show_node_types": ["PERSON", "made_up"], "show_edge_types": []},
        )
        out = await ask_graph(snap, "Who is Maya?", model=model)
        assert out.stopped == "answered"
        assert out.highlight_node_ids == ["p-maya"]  # unknown handle dropped
        assert out.node_types == []  # one bad type rejects the filter rather than half-applying it
        assert [s["tool"] for s in out.steps] == ["search_nodes", "get_node"]
        assert f'{maya} person "Maya Okafor"' in results[0]
        assert "relationship_type" in results[1] and "-FREQUENTS->" in results[1]
        assert "p-maya" not in results[1]  # real ids never reach the model

    async def test_tool_errors_are_actionable(self, snap):
        model, results = scripted(
            ("get_node", {"node": "n999"}),
            ("traverse", {"start": snap.handle("u1"), "edge_types": ["LOVES"]}),
            ("find_path", {"source": snap.handle("p-maya"), "target": snap.handle("t-trip")}),
            {"answer": "ok"},
        )
        await ask_graph(snap, "x", model=model)
        assert "search_nodes" in results[0]
        assert "Known edge types" in results[1] and "KNOWS" in results[1]
        assert results[2].startswith("2 hop(s):")

    async def test_view_filter_is_case_insensitive(self, snap):
        model, _ = scripted({"answer": "Showing people and pets.", "show_node_types": ["Person", "pet"]})
        out = await ask_graph(snap, "show only people and pets", model=model)
        assert out.to_dict()["filter"] == {"node_types": ["person", "pet"], "edge_types": []}

    async def test_step_limit_is_a_clean_exit(self, snap):
        def loop(messages, info):
            return ModelResponse(parts=[ToolCallPart("search_nodes", {"query": "Maya Okafor"})])

        out = await ask_graph(snap, "loop forever", model=FunctionModel(loop), max_requests=3)
        assert out.stopped == "step_limit"
        assert "3 steps" in out.answer
        assert out.highlight_node_ids[0] == "p-maya"  # nodes it had looked at

    async def test_model_failure_is_a_clean_exit(self, snap):
        def boom(messages, info):
            raise RuntimeError("upstream down")

        out = await ask_graph(snap, "x", model=FunctionModel(boom))
        assert out.stopped == "error"
        assert "upstream down" not in out.answer

    async def test_summary_and_selection_reach_the_model(self, snap):
        captured: dict = {}

        def run(messages, info: AgentInfo):
            captured["instructions"] = info.instructions or messages[0].instructions
            captured["prompt"] = messages[0].parts[-1].content
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"answer": "ok"})])

        await ask_graph(snap, "what is this?", model=FunctionModel(run), selected_id="l-cafe",
                        history=[{"question": "earlier q", "answer": "earlier a"}])
        assert "pet (2)" in captured["instructions"]
        assert "Blue Door Coffee" in captured["instructions"]
        assert "earlier q" in captured["prompt"] and captured["prompt"].endswith("what is this?")


class TestScorer:
    def test_all_checks(self):
        case = GraphCase.model_validate({
            "id": "c", "question": "q",
            "expect": {"mentions": ["Biscuit"], "not_mentions": ["12 pets"], "highlight": ["pet-biscuit"],
                       "tools_any": ["search_nodes"], "max_tool_calls": 2, "node_types": ["pet"]},
        })
        good = {"answer": "You have Biscuit.", "stopped": "answered", "highlight_node_ids": ["pet-biscuit", "x"],
                "steps": [{"tool": "search_nodes"}], "filter": {"node_types": ["pet"], "edge_types": []}}
        assert all(score_case(case, good).values())
        bad = {**good, "answer": "You have 12 pets.", "steps": [{"tool": "get_node"}] * 3, "filter": None}
        failed = {k for k, ok in score_case(case, bad).items() if not ok}
        assert failed == {"mentions", "not_mentions", "tools", "step_budget", "node_filter"}

    def test_fixture_is_self_consistent(self):
        suite = load_graph_suite()
        snap = suite.snapshot()
        assert len(snap.edges) == len(suite.graph["edges"])
        for case in suite.cases:
            for node_id in [*case.expect.highlight, *([case.selected] if case.selected else [])]:
                assert snap.node(node_id), f"{case.id}: unknown node {node_id}"
