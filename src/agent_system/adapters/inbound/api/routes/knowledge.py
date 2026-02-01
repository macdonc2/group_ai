"""Knowledge graph API routes."""

from fastapi import APIRouter, Depends, HTTPException

from agent_system.adapters.inbound.api.dependencies import CurrentUserId, get_current_user
from agent_system.composition_root.container import get_container
from agent_system.domain.entities import User


router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/graph")
async def get_user_knowledge_graph(
    current_user_id: CurrentUserId,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Get the knowledge graph data for the current user.
    
    Returns nodes and links in a format suitable for visualization.
    """
    container = await get_container()
    
    if not container.knowledge_graph_adapter:
        raise HTTPException(
            status_code=503,
            detail="Knowledge graph service not available"
        )
    
    try:
        # Fix user node label if it's showing UUID instead of email
        # This runs a one-time update to correct old nodes
        await container.knowledge_graph_adapter.update_user_label(
            user_id=current_user_id,
            label=current_user.email,
        )
        
        # Get all nodes connected to the user
        from agent_system.domain.entities import KnowledgeNodeType
        
        # Get user's nodes
        user_nodes = await container.knowledge_graph_adapter.get_user_nodes(
            user_id=current_user_id,
            node_type=None,  # All types
        )
        
        # Build response with nodes and links
        nodes = []
        links = []
        node_ids = set()
        
        # Color mapping for node types
        type_colors = {
            "user": "#3b82f6",       # blue
            "interaction": "#10b981", # green
            "topic": "#f59e0b",       # amber
            "tool": "#8b5cf6",        # purple
            "suggestion": "#ec4899",  # pink
        }
        
        # Add all nodes
        for node in user_nodes:
            node_ids.add(str(node.id))
            nodes.append({
                "id": str(node.id),
                "label": node.label[:30] + "..." if len(node.label) > 30 else node.label,
                "fullLabel": node.label,
                "type": node.node_type.value,
                "color": type_colors.get(node.node_type.value, "#6b7280"),
                "properties": node.properties,
            })
        
        # Get relationships for each node
        for node in user_nodes:
            try:
                relationships = await container.knowledge_graph_adapter.get_relationships(
                    node_id=node.id,
                    direction="both",
                )
                
                for rel in relationships:
                    source = str(rel.source_id)
                    target = str(rel.target_id)
                    
                    # Only include links where both nodes are in our set
                    if source in node_ids and target in node_ids:
                        links.append({
                            "source": source,
                            "target": target,
                            "type": rel.relation_type.value,
                            "label": rel.relation_type.value.replace("_", " "),
                        })
            except Exception:
                # Skip relationships that fail
                continue
        
        # Deduplicate links
        seen_links = set()
        unique_links = []
        for link in links:
            key = f"{link['source']}-{link['target']}-{link['type']}"
            if key not in seen_links:
                seen_links.add(key)
                unique_links.append(link)
        
        return {
            "nodes": nodes,
            "links": unique_links,
            "stats": {
                "total_nodes": len(nodes),
                "total_links": len(unique_links),
                "node_types": {
                    node_type: sum(1 for n in nodes if n["type"] == node_type)
                    for node_type in set(n["type"] for n in nodes)
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
