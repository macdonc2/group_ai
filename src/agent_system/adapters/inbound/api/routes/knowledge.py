"""Knowledge graph API routes."""

from fastapi import APIRouter, Depends, HTTPException

from agent_system.adapters.inbound.api.dependencies import CurrentUserId, get_current_user
from agent_system.composition_root.container import get_container
from agent_system.domain.entities import User
from agent_system.domain.value_objects import KnowledgeNodeId


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
}


def _node_label(text: str, max_len: int = 30) -> str:
    """Truncate label for display."""
    return text[:max_len] + "..." if len(text) > max_len else text


@router.get("/graph")
async def get_user_knowledge_graph(
    current_user_id: CurrentUserId,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Get the full knowledge graph for the current user.

    Returns nodes and links for visualization: KnowledgeNodes (user, topic,
    tool, interaction, suggestion) plus social graph nodes (person, pet,
    location) as one unified graph.
    """
    container = await get_container()

    if not container.knowledge_graph_adapter:
        raise HTTPException(
            status_code=503,
            detail="Knowledge graph service not available"
        )

    try:
        kg = container.knowledge_graph_adapter

        # Fix user node label if needed
        await kg.update_user_label(
            user_id=current_user_id,
            label=current_user.email,
        )

        # 1. Knowledge nodes (user, topic, tool, interaction, suggestion)
        user_nodes = await kg.get_user_nodes(
            user_id=current_user_id,
            node_type=None,
        )

        nodes: list[dict] = []
        node_ids: set[str] = set()

        for node in user_nodes:
            node_ids.add(str(node.id))
            nodes.append({
                "id": str(node.id),
                "label": _node_label(node.label),
                "fullLabel": node.label,
                "type": node.node_type.value,
                "color": TYPE_COLORS.get(node.node_type.value, "#6b7280"),
                "properties": node.properties,
            })

        # 2. Social graph nodes (person, pet, location)
        people = await kg.list_known_people(current_user_id)
        pets = await kg.list_pets(current_user_id)
        locations = await kg.list_locations(current_user_id)

        for p in people or []:
            nid = p.get("id") or p.get("name", "")
            if nid and str(nid) not in node_ids:
                node_ids.add(str(nid))
                name = p.get("name", str(nid))
                rel = p.get("relationship_type", "")
                full = f"{name}" + (f" ({rel})" if rel else "")
                nodes.append({
                    "id": str(nid),
                    "label": _node_label(name),
                    "fullLabel": full,
                    "type": "person",
                    "color": TYPE_COLORS["person"],
                    "properties": dict(p),
                })

        for p in pets or []:
            nid = p.get("id") or p.get("name", "")
            if nid and str(nid) not in node_ids:
                node_ids.add(str(nid))
                name = p.get("name", str(nid))
                species = p.get("species", "")
                full = f"{name}" + (f" ({species})" if species else "")
                nodes.append({
                    "id": str(nid),
                    "label": _node_label(name),
                    "fullLabel": full,
                    "type": "pet",
                    "color": TYPE_COLORS["pet"],
                    "properties": dict(p),
                })

        for loc in locations or []:
            nid = loc.get("id") or loc.get("name", "")
            if nid and str(nid) not in node_ids:
                node_ids.add(str(nid))
                name = loc.get("name", str(nid))
                loc_type = loc.get("location_type", "")
                full = f"{name}" + (f" ({loc_type})" if loc_type else "")
                nodes.append({
                    "id": str(nid),
                    "label": _node_label(name),
                    "fullLabel": full,
                    "type": "location",
                    "color": TYPE_COLORS["location"],
                    "properties": dict(loc),
                })

        # 3. Relationships: KnowledgeNodes + User->Person/Pet/Location
        links: list[dict] = []
        all_node_refs: list[dict] = [{"id": str(n.id)} for n in user_nodes]
        all_node_refs += [{"id": n["id"]} for n in nodes if n["type"] in ("person", "pet", "location")]

        for node_ref in all_node_refs:
            nid = node_ref.get("id")
            if not nid:
                continue
            try:
                rels = await kg.get_relationships(
                    node_id=KnowledgeNodeId.from_string(str(nid)),
                    direction="both",
                )
                for rel in rels:
                    src = str(rel.source_id)
                    tgt = str(rel.target_id)
                    if src in node_ids and tgt in node_ids:
                        links.append({
                            "source": src,
                            "target": tgt,
                            "type": rel.relation_type.value,
                            "label": rel.relation_type.value.replace("_", " "),
                        })
            except Exception:
                continue

        # Deduplicate links
        seen: set[str] = set()
        unique_links: list[dict] = []
        for link in links:
            key = f"{link['source']}-{link['target']}-{link['type']}"
            if key not in seen:
                seen.add(key)
                unique_links.append(link)

        return {
            "nodes": nodes,
            "links": unique_links,
            "stats": {
                "total_nodes": len(nodes),
                "total_links": len(unique_links),
                "node_types": {
                    t: sum(1 for n in nodes if n["type"] == t)
                    for t in set(n["type"] for n in nodes)
                }
            }
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve knowledge graph: {str(e)}"
        )


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
