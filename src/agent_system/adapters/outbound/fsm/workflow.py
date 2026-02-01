"""Agent workflow graph definition."""

from pydantic_graph import Graph

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
    
    Args:
        user_input: The user's input message
        state: The current workflow state
        deps: Dependencies for the workflow
        
    Returns:
        The workflow result with response and suggestions
    """
    # Create the initial node
    start_node = ReceiveInput(user_input=user_input)
    
    # Run the workflow
    result = await agent_workflow.run(
        start_node,
        state=state,
        deps=deps,
    )
    
    return result.output


def generate_workflow_diagram() -> str:
    """Generate a Mermaid diagram of the workflow.
    
    Returns:
        Mermaid diagram code as a string
    """
    return agent_workflow.mermaid_code(start_node=ReceiveInput)
