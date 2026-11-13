"""Agent workflow graph definition."""

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

    if chat_engine_for(state, deps) == "loop":
        return await _run_loop_engine(user_input, state, deps, trace)

    with bind_trace(trace):
        node_token = set_current_node(None)
        try:
            async with agent_workflow.iter(ReceiveInput(user_input=user_input), state=state, deps=deps) as run:
                async for node in run:
                    if isinstance(node, End):
                        break
                    name = type(node).__name__
                    trace.enter_node(name)
                    set_current_node(name)
            output = run.result.output
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
