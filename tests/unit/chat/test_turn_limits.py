"""Explicit exits: whole-turn timeout and model-call cap, research lane/job limits, turn-outcome labels."""

import asyncio
from types import SimpleNamespace

import pytest

from agent_system.adapters.outbound.fsm import nodes, workflow
from agent_system.adapters.outbound.fsm.state import AgentDependencies, WorkflowState
from agent_system.adapters.outbound.research import lanes
from agent_system.adapters.outbound.telemetry import TurnTrace
from agent_system.domain.entities import Conversation, User

pytestmark = pytest.mark.unit


def _turn(**limits):
    user = User.create(email="limits@example.com", hashed_password="x")
    state = WorkflowState(user=user, conversation=Conversation.create(user_id=user.id))
    events: list[str] = []

    async def on_event(event_type, node, message, data):
        events.append(event_type)

    deps = AgentDependencies(llm_port=None, user_repository=None, conversation_repository=None,
                             plan_repository=None, knowledge_graph_port=None, event_callback=on_event)
    deps.chat_engine = "fsm"
    for key, value in limits.items():
        setattr(deps, key, value)
    return state, deps, events


class TestTurnLimits:
    async def test_fsm_turn_times_out_cleanly(self, monkeypatch):
        async def hang(self, ctx):
            await asyncio.sleep(5)

        monkeypatch.setattr(nodes.AnalyzeIntent, "run", hang)
        state, deps, events = _turn(turn_timeout_s=0.05)
        result = await workflow.run_agent_workflow("hello", state, deps)
        assert result.error == "timeout" and "longer than" in result.response
        assert deps.trace.error == "timeout"
        assert events[-1] == "response"  # the UI still gets its final event

    async def test_reply_already_written_survives_a_late_timeout(self, monkeypatch):
        async def reply_then_hang(self, ctx):
            ctx.state.response = "Here is your answer."
            await asyncio.sleep(5)

        monkeypatch.setattr(nodes.AnalyzeIntent, "run", reply_then_hang)
        state, deps, _ = _turn(turn_timeout_s=0.05)
        result = await workflow.run_agent_workflow("hello", state, deps)
        assert result.response == "Here is your answer." and result.error is None
        assert deps.trace.error == "timeout"  # the trace still records that post-reply work was cut

    async def test_fsm_turn_stops_at_the_model_call_cap(self, monkeypatch):
        async def chatty(self, ctx):
            ctx.deps.trace.llm_calls.extend([SimpleNamespace()] * 5)
            return nodes.UpdateKnowledge()

        ran: list[str] = []

        async def must_not_run(self, ctx):
            ran.append("UpdateKnowledge")
            return nodes.CheckPlan()

        monkeypatch.setattr(nodes.AnalyzeIntent, "run", chatty)
        monkeypatch.setattr(nodes.UpdateKnowledge, "run", must_not_run)
        state, deps, events = _turn(turn_max_llm_calls=3)
        result = await workflow.run_agent_workflow("hello", state, deps)
        assert result.error == "step_limit" and "3 model calls" in result.response
        assert ran == [] and events[-1] == "response"


class TestResearchLimits:
    async def test_slow_lane_fails_alone(self, monkeypatch):
        from agent_system.domain.entities.research import LaneResult

        async def fake_lane(lane, question, deps, emit):
            if lane == "practical":
                await asyncio.sleep(5)
            return LaneResult(lane=lane, queries=[f"{lane} query"])

        emitted: list[tuple[str, str]] = []

        async def emit(event_type, node, message, data):
            emitted.append((event_type, node))

        monkeypatch.setattr(lanes, "run_lane", fake_lane)
        results = await lanes.run_all_lanes("q", deps=SimpleNamespace(lane_timeout_s=0.05), emit=emit)
        assert results["practical"].error == "timed out after 0 s"
        assert results["academic"].error is None and results["empirical"].queries == ["empirical query"]
        assert emitted == [("lane_error", "practical")]

    async def test_jobs_beyond_the_cap_wait_and_a_job_has_a_time_limit(self, monkeypatch):
        from agent_system.adapters.outbound.research import runner as runner_mod

        updates: list[dict] = []
        running = 0
        peak = 0

        class Runner(runner_mod.ResearchRunner):
            async def _run_pipeline(self, job_id, api_key, live, trace):
                nonlocal running, peak
                running += 1
                peak = max(peak, running)
                try:
                    await asyncio.sleep(5 if job_id == "slow" else 0.02)
                finally:
                    running -= 1

            async def _update(self, job_id, **fields):
                updates.append({"job": job_id, **fields})

        settings = runner_mod.ResearchSettings(strong_model="m", fast_model="m", tts_model="t", tts_voice="v",
                                               job_timeout_s=0.1, max_concurrent_jobs=1)
        r = Runner(database=None, settings=settings)
        for job in ("a", "b", "slow"):
            r.start(job, "key")
        await asyncio.gather(*(r._jobs[j].task for j in ("a", "b", "slow")))
        assert peak == 1  # never two at once
        assert updates == [{"job": "slow", "error": "Stopped after 0 seconds (job time limit)"}]


def test_turn_outcome_labels_stay_low_cardinality():
    from agent_system.adapters.outbound.persistence.trace_repository import turn_outcome

    assert [turn_outcome(e) for e in (None, "", "timeout", "step_limit", "RuntimeError: boom")] == [
        "ok", "ok", "timeout", "step_limit", "error"]
