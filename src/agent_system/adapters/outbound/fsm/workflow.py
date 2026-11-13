"""Agent workflow graph definition."""

import asyncio

from pydantic_graph import End, Graph

from agent_system.adapters.outbound.fsm.nodes import (
    AnalyzeIntent,
    CheckPlan,
    CreatePlan,
    EvaluateResult,
    ExecutePlan,
    ExecuteTool,
    FinalizeKnowledge,
    GenerateResponse,
    ReceiveInput,
    SelectTool,
    UpdateKnowledge,
)
from agent_system.adapters.outbound.fsm.state import (
    AgentDependencies,
    WorkflowResult,
    WorkflowState,
)
from agent_system.adapters.outbound.telemetry import (
    TurnTrace,
    bind_trace,
    install_llm_capture,
    set_current_node,
)


# Define the agent workflow graph
agent_workflow: Graph[WorkflowState, AgentDependencies, WorkflowResult] = Graph(
    nodes=[
        ReceiveInput,
        AnalyzeIntent,
        UpdateKnowledge,
        CheckPlan,
        CreatePlan,
        ExecutePlan,
        SelectTool,
        ExecuteTool,
        EvaluateResult,
        GenerateResponse,
        FinalizeKnowledge,
    ],
)


async def run_agent_workflow(
    user_input: str,
    state: WorkflowState,
    deps: AgentDependencies,
) -> WorkflowResult:
    """Run the agent workflow for a user input.

    Every run is traced: each node visit becomes a span, and LLM/embedding
    usage is attributed to the node that made it. The trace is left on
    `deps.trace` for the caller to persist.

    Args:
        user_input: The user's input message
        state: The current workflow state
        deps: Dependencies for the workflow

    Returns:
        The workflow result with response and suggestions
    """
    install_llm_capture()
    trace = deps.trace if deps.trace is not None else TurnTrace()
    trace.user_input = user_input
    deps.trace = trace

    timeout_s, max_llm_calls = _turn_limits(deps)
    engine = _run_loop_engine if chat_engine_for(state, deps) == "loop" else _run_fsm_engine
    try:
        return await asyncio.wait_for(engine(user_input, state, deps, trace, max_llm_calls), timeout=timeout_s)
    except TimeoutError:
        return await _stopped_turn(state, deps, trace, "timeout",
                                   f"That took longer than {int(timeout_s)} seconds, so I stopped. Please try again "
                                   "or ask for one part at a time.")
    except TurnLimitExceeded:
        return await _stopped_turn(state, deps, trace, "step_limit",
                                   f"I stopped after {max_llm_calls} model calls without finishing. Could you ask for "
                                   "one part of that at a time?")


class TurnLimitExceeded(Exception):
    """A turn made more model calls than `chat_turn_max_llm_calls` allows."""


def _turn_limits(deps: AgentDependencies) -> tuple[float, int]:
    """(wall-clock seconds, model calls) allowed for one turn. `deps` attributes override the settings."""
    from agent_system.composition_root.config import get_settings

    settings = get_settings()
    return (
        float(getattr(deps, "turn_timeout_s", None) or settings.chat_turn_timeout_s),
        int(getattr(deps, "turn_max_llm_calls", None) or settings.chat_turn_max_llm_calls),
    )


async def _stopped_turn(state: WorkflowState, deps: AgentDependencies, trace: TurnTrace, reason: str,
                        message: str) -> WorkflowResult:
    """A turn that hit a limit still ends cleanly: a reply, a final event, a finished trace.

    If the reply was already written (the limit hit during post-reply memory work), the user
    gets that reply; only the memory step was cut short.
    """
    had_reply = bool(state.response and state.response.strip())
    if not had_reply:
        state.response = message
        state.error = reason
    deps.decide("Workflow", f"turn limit: {reason}", True, "End", had_reply=had_reply)
    await deps.emit_event("response", "Workflow", "Workflow complete", {
        "response": state.response, "suggestions": [], "tools_used": [state.tool_name] if state.tool_name else [],
    })
    trace.finish(response=state.response, error=reason)
    return WorkflowResult.from_state(state)


async def _run_fsm_engine(
    user_input: str,
    state: WorkflowState,
    deps: AgentDependencies,
    trace: TurnTrace,
    max_llm_calls: int,
) -> WorkflowResult:
    with bind_trace(trace):
        node_token = set_current_node(None)
        try:
            async with agent_workflow.iter(ReceiveInput(user_input=user_input), state=state, deps=deps) as run:
                async for node in run:
                    if isinstance(node, End):
                        break
                    if len(trace.llm_calls) > max_llm_calls:  # checked between nodes; a node finishes its own calls
                        raise TurnLimitExceeded
                    name = type(node).__name__
                    trace.enter_node(name)
                    set_current_node(name)
            output = run.result.output
        except TurnLimitExceeded:
            raise
        except Exception as exc:
            trace.finish(error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            node_token.var.reset(node_token)

    trace.finish(response=output.response)
    return output


def chat_engine_for(state: WorkflowState, deps: AgentDependencies) -> str:
    """Which engine runs this turn. `deps.chat_engine` (evals, tests) overrides the setting."""
    if state.group_context:  # group turns stay on the FSM until they have their own tool profile
        return "fsm"
    engine = getattr(deps, "chat_engine", None)
    if engine is None:
        from agent_system.composition_root.config import get_settings

        engine = get_settings().chat_engine
    return "loop" if engine == "loop" else "fsm"


async def _run_loop_engine(
    user_input: str,
    state: WorkflowState,
    deps: AgentDependencies,
    trace: TurnTrace,
    max_llm_calls: int = 30,
) -> WorkflowResult:
    """One turn through the single tool loop, then the FSM's own post-reply step.

    The loop replaces AnalyzeIntent .. GenerateResponse. FinalizeKnowledge (memory extraction,
    suggestions, embeddings, the final `response` event) is reused unchanged so both engines
    learn from a turn in the same way.
    """
    from pydantic_graph import GraphRunContext

    from agent_system.adapters.outbound.llm.agents import _get_model
    from agent_system.adapters.outbound.llm.chat_agent import ChatDeps, build_history, run_chat_loop
    from agent_system.composition_root.config import get_settings

    settings = get_settings()
    state.user_input = user_input
    state.is_complete = False
    state.error = None

    with bind_trace(trace):
        node_token = set_current_node("ChatLoop")
        try:
            trace.enter_node("ChatLoop")
            await deps.emit_event("node_start", "ChatLoop", "Thinking...")
            outcome = await run_chat_loop(
                user_input,
                deps=ChatDeps(
                    user_id=str(state.user.id),
                    timezone=state.user.timezone,
                    knowledge_graph_port=deps.knowledge_graph_port,
                    embedding_port=deps.embedding_port,
                    notes=[p.description for p in state.user.learned_patterns[-5:]],
                    persona=deps.persona,
                    trace=trace,
                    emit=deps.emit_event,
                ),
                model=getattr(deps, "chat_loop_model", None) or _get_model(deps.default_model, deps.openai_api_key),
                history=build_history(state.conversation.get_context_messages(), user_input),
                max_requests=settings.chat_loop_max_requests,
                timeout_s=settings.chat_loop_timeout_s,
            )
            answered = outcome.stopped == "answered"
            deps.decide("ChatLoop", "loop ended with an answer", answered, "FinalizeKnowledge" if answered else "End",
                        stopped=outcome.stopped, requests=outcome.requests, tools=outcome.tools_used)

            state.response = outcome.response
            state.tool_name = outcome.tools_used[0] if outcome.tools_used else None
            state.tool_result = outcome.steps[-1]["summary"] if outcome.steps else None
            if not outcome.streamed:  # limit and error messages, or a model that could not stream
                await deps.emit_event("response_chunk", "ChatLoop", outcome.response,
                                      {"accumulated_length": len(outcome.response)})
            await deps.emit_event("node_complete", "ChatLoop", f"Loop finished: {outcome.stopped}",
                                  {"stopped": outcome.stopped, "tools_used": outcome.tools_used})

            if answered:
                trace.enter_node("FinalizeKnowledge")
                set_current_node("FinalizeKnowledge")
                end = await FinalizeKnowledge().run(GraphRunContext(state=state, deps=deps))
                output = end.data
            else:  # nothing worth remembering from a failed turn
                state.error = outcome.stopped
                await deps.emit_event("response", "ChatLoop", "Workflow complete",
                                      {"response": state.response, "suggestions": [], "tools_used": outcome.tools_used})
                output = WorkflowResult.from_state(state)
            output.tools_used = outcome.tools_used
        except Exception as exc:
            trace.finish(error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            node_token.var.reset(node_token)

    trace.finish(response=output.response, error=None if answered else outcome.stopped)
    return output


def workflow_topology() -> dict:
    """Static FSM topology (nodes and labelled edges) for the predicate-tree viewer."""
    nodes = []
    edges = []
    for node_id, node_def in agent_workflow.node_defs.items():
        nodes.append({"id": node_id, "doc": (node_def.node.__doc__ or "").strip()})
        for target, edge in node_def.next_node_edges.items():
            edges.append({"source": node_id, "target": target, "label": edge.label})
        if node_def.end_edge is not None:
            edges.append({"source": node_id, "target": "End", "label": node_def.end_edge.label})
    nodes.append({"id": "End", "doc": "Workflow result returned"})
    return {"start": "ReceiveInput", "nodes": nodes, "edges": edges}


def generate_workflow_diagram() -> str:
    """Generate a Mermaid diagram of the workflow.

    Returns:
        Mermaid diagram code as a string
    """
    return agent_workflow.mermaid_code(start_node=ReceiveInput)
