"""CheckPlan: a tool that is the whole task is used, not replaced by a plan.

The bug this pins: "Summarize this page for me: <url>" is a command, so its intent is `task`.
The router picked `read_webpage` and said no planning was needed, but CheckPlan planned every
task anyway. The planner then chose its own steps and the page was never read.
"""

from types import SimpleNamespace

import pytest

from agent_system.adapters.outbound.fsm.nodes import CheckPlan, CreatePlan, ExecutePlan
from agent_system.domain.value_objects import IntentType

pytestmark = pytest.mark.unit


def context(*, intent=IntentType.TASK, tool=None, requires_planning=False, auto_plan=True):
    decisions = []

    def decide(node, predicate, result, next_node, **inputs):
        decisions.append({"predicate": predicate, "result": result, "next": next_node, "inputs": inputs})
        return result

    async def emit_event(*args, **kwargs):
        return None

    state = SimpleNamespace(
        conversation=SimpleNamespace(active_plan_id=None),
        user=SimpleNamespace(preferences=SimpleNamespace(auto_plan=auto_plan)),
        intent=SimpleNamespace(intent_type=intent),
        plan_needed=requires_planning, requires_tool=tool is not None, tool_name=tool,
        react_mode=False, step_results=None, current_step_index=None,
    )
    return SimpleNamespace(state=state, deps=SimpleNamespace(decide=decide, emit_event=emit_event)), decisions


async def test_a_command_to_read_a_page_reads_it_instead_of_planning():
    ctx, decisions = context(intent=IntentType.TASK, tool="read_webpage")
    assert isinstance(await CheckPlan().run(ctx), ExecutePlan)
    assert ctx.state.react_mode is False
    assert ctx.state.tool_name == "read_webpage"
    assert decisions[-1]["inputs"]["direct_tool"] is True
    assert decisions[-1]["inputs"]["suggested_tool"] == "read_webpage"


@pytest.mark.parametrize("tool", ["web_search", "recall_about_topic", "get_houston_events"])
async def test_a_task_that_names_an_information_tool_is_still_planned(tool):
    # A first attempt let any chosen tool skip planning. The evals caught it: the router names
    # web_search for "plan a 3-day road trip" and recall_about_topic for "plan a birthday dinner",
    # and those stopped being planned.
    ctx, decisions = context(intent=IntentType.TASK, tool=tool)
    assert isinstance(await CheckPlan().run(ctx), CreatePlan)
    assert decisions[-1]["inputs"]["direct_tool"] is False


async def test_a_task_with_no_tool_is_still_planned():
    ctx, _ = context(intent=IntentType.TASK, tool=None)
    assert isinstance(await CheckPlan().run(ctx), CreatePlan)
    assert ctx.state.react_mode is True


async def test_an_explicit_request_for_planning_is_always_planned():
    ctx, _ = context(intent=IntentType.QUESTION, requires_planning=True)
    assert isinstance(await CheckPlan().run(ctx), CreatePlan)
    # An explicit requires_planning wins even over a page read: the router asked for reasoning.
    ctx, _ = context(intent=IntentType.QUESTION, requires_planning=True, tool="read_webpage")
    assert isinstance(await CheckPlan().run(ctx), CreatePlan)


async def test_auto_plan_off_never_plans():
    ctx, _ = context(intent=IntentType.TASK, tool=None, auto_plan=False)
    assert isinstance(await CheckPlan().run(ctx), ExecutePlan)
