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
