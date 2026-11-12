"""Knowledge graph API routes: the graph itself and the graph explorer agent."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agent_system.adapters.inbound.api.dependencies import (
    CurrentUserId,
    SessionDep,
    get_current_user,
)
from agent_system.application.services.graph_explorer import GraphSnapshot, clean_properties
from agent_system.composition_root.container import get_container
from agent_system.domain.entities import User
from agent_system.domain.value_objects import UserId

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

# Color mapping for all node types (single master graph)
TYPE_COLORS = {
    "user": "#3b82f6",       # blue
    "interaction": "#10b981",  # green
    "topic": "#f59e0b",       # amber
    "tool": "#8b5cf6",        # purple
    "suggestion": "#ec4899",  # pink
    "person": "#06b6d4",      # cyan
    "pet": "#84cc16",         # lime
    "location": "#f97316",    # orange
    "preference": "#eab308",  # yellow
    "pattern": "#14b8a6",     # teal
    "thread": "#a855f7",      # violet
    "expertise": "#f43f5e",   # rose
    "entity": "#0ea5e9",      # sky
    "intent": "#64748b",      # slate
    "contradiction": "#ef4444",  # red
}


def _node_label(text: str, max_len: int = 30) -> str:
    """Truncate label for display."""
    return text[:max_len] + "..." if len(text) > max_len else text


async def _load_snapshot(current_user_id: str) -> GraphSnapshot:
    """The current user's graph, scoped to their own data."""
    container = await get_container()
    if not container.knowledge_graph_adapter:
        raise HTTPException(status_code=503, detail="Knowledge graph service not available")
    nodes, edges = await container.knowledge_graph_adapter.get_user_subgraph(UserId.from_string(current_user_id))
    return GraphSnapshot.from_records(nodes, edges)


@router.get("/graph")
async def get_user_knowledge_graph(
    current_user_id: CurrentUserId,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Get the full knowledge graph for the current user.

    Returns nodes and links for visualization: KnowledgeNodes (user, topic,
    tool, interaction, suggestion, ...) plus social graph nodes (person, pet,
    location) as one unified graph.
    """
    container = await get_container()
    if not container.knowledge_graph_adapter:
        raise HTTPException(status_code=503, detail="Knowledge graph service not available")

    try:
        # Fix user node label if needed
        await container.knowledge_graph_adapter.update_user_label(
            user_id=current_user_id,
            label=current_user.email,
        )
        snapshot = await _load_snapshot(current_user_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve knowledge graph: {str(e)}")

    nodes = []
    for node in snapshot.nodes:
        detail = node.properties.get("relationship_type") or node.properties.get("species") \
            or node.properties.get("location_type")
        nodes.append({
            "id": node.id,
            "label": _node_label(node.label),
            "fullLabel": f"{node.label} ({detail})" if detail else node.label,
            "type": node.type,
            "color": TYPE_COLORS.get(node.type, "#6b7280"),
            "degree": snapshot.degree(node.id),
            "properties": clean_properties(node.properties),
        })
    links = [
        {"source": e.source, "target": e.target, "type": e.type, "label": e.type.replace("_", " ").lower()}
        for e in snapshot.edges
    ]
    return {
        "nodes": nodes,
        "links": links,
        "stats": {
            "total_nodes": len(nodes),
            "total_links": len(links),
            "node_types": snapshot.node_type_counts(),
            "edge_types": snapshot.edge_type_counts(),
        },
    }


class GraphTurn(BaseModel):
    question: str = Field(max_length=2000)
    answer: str = Field(max_length=8000)


class GraphAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    selected_node_id: str | None = Field(default=None, max_length=64)
    history: list[GraphTurn] = Field(default_factory=list, max_length=6)


@router.post("/graph/ask")
async def ask_knowledge_graph(
    payload: GraphAskRequest,
    current_user_id: CurrentUserId,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Ask the graph explorer agent a question about the current user's graph.

    The agent only reads; the response carries the answer plus validated node
    ids to highlight and (when the user asked for one) a type filter to apply.
    """
    from agent_system.adapters.inbound.api.routes.research import _resolve_api_key
    from agent_system.adapters.outbound.llm.agents import _get_model
    from agent_system.adapters.outbound.llm.graph_agent import ask_graph
    from agent_system.adapters.outbound.persistence.trace_repository import save_turn_trace
    from agent_system.adapters.outbound.telemetry import TurnTrace, bind_trace, install_llm_capture
    from agent_system.composition_root.config import get_settings

    settings = get_settings()
    api_key = _resolve_api_key(current_user, settings)
    try:
        snapshot = await _load_snapshot(current_user_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve knowledge graph: {str(e)}")

    install_llm_capture()
    trace = TurnTrace(user_input=payload.question)
    trace.enter_node("GraphExplorer")
    with bind_trace(trace):
        result = await ask_graph(
            snapshot,
            payload.question.strip(),
            model=_get_model(settings.graph_agent_model or settings.default_model, api_key),
            selected_id=payload.selected_node_id,
            history=[t.model_dump() for t in payload.history],
            max_requests=settings.graph_agent_max_requests,
            timeout_s=settings.graph_agent_timeout_s,
        )
    for step in result.steps:
        trace.add_tool_call(step["tool"], step["args"], step["summary"], True, step["duration_ms"])
    trace.finish(response=result.answer, error=None if result.stopped == "answered" else result.stopped)
    await save_turn_trace(
        trace, user_id=current_user_id, conversation_id="graph-explorer", source="graph", session=session,
    )

    data = result.to_dict()
    data["usage"]["cost_usd"] = trace.usage()["cost_usd"]
    return data


@router.delete("/graph")
async def clear_user_knowledge_graph(
    current_user_id: CurrentUserId,
) -> dict:
    """Clear the knowledge graph for the current user."""
    container = await get_container()
    
    if not container.knowledge_graph_adapter:
        raise HTTPException(
            status_code=503,
            detail="Knowledge graph service not available"
        )
    
    try:
        deleted = await container.knowledge_graph_adapter.clear_user_graph(
            user_id=current_user_id
        )
        return {"deleted_nodes": deleted}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to clear knowledge graph: {str(e)}"
        )
