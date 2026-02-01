"""Knowledge entity - represents nodes in the knowledge graph."""

from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, Field

from agent_system.domain.value_objects import (
    Entity,
    Intent,
    KnowledgeNodeId,
    Relationship,
    RelationType,
    Suggestion,
    UserId,
)


class KnowledgeNodeType(str, Enum):
    """Type of knowledge node."""

    USER = "user"
    INTENT = "intent"
    TOPIC = "topic"
    TOOL = "tool"
    INTERACTION = "interaction"
    SUGGESTION = "suggestion"
    ENTITY = "entity"


class KnowledgeNode(BaseModel):
    """A node in the knowledge graph."""

    id: KnowledgeNodeId
    node_type: KnowledgeNodeType
    label: str
    properties: Annotated[dict[str, Any], Field(default_factory=dict)]
    created_at: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    updated_at: Annotated[datetime, Field(default_factory=datetime.utcnow)]

    @classmethod
    def create_user_node(cls, user_id: UserId, email: str) -> "KnowledgeNode":
        """Create a user node."""
        return cls(
            id=KnowledgeNodeId.generate(),
            node_type=KnowledgeNodeType.USER,
            label=email,
            properties={"user_id": str(user_id)},
        )

    @classmethod
    def create_intent_node(cls, intent: Intent) -> "KnowledgeNode":
        """Create an intent node from an Intent value object."""
        return cls(
            id=KnowledgeNodeId.generate(),
            node_type=KnowledgeNodeType.INTENT,
            label=intent.description,
            properties={
                "intent_type": intent.intent_type.value,
                "confidence": intent.confidence,
                "entities": intent.entities,
            },
        )

    @classmethod
    def create_topic_node(cls, topic: str, description: str | None = None) -> "KnowledgeNode":
        """Create a topic node."""
        return cls(
            id=KnowledgeNodeId.generate(),
            node_type=KnowledgeNodeType.TOPIC,
            label=topic,
            properties={"description": description} if description else {},
        )

    @classmethod
    def create_tool_node(cls, tool_name: str, description: str | None = None) -> "KnowledgeNode":
        """Create a tool node."""
        return cls(
            id=KnowledgeNodeId.generate(),
            node_type=KnowledgeNodeType.TOOL,
            label=tool_name,
            properties={"description": description} if description else {},
        )

    @classmethod
    def create_interaction_node(
        cls,
        summary: str,
        conversation_id: str,
        timestamp: datetime | None = None,
    ) -> "KnowledgeNode":
        """Create an interaction node."""
        return cls(
            id=KnowledgeNodeId.generate(),
            node_type=KnowledgeNodeType.INTERACTION,
            label=summary,
            properties={
                "conversation_id": conversation_id,
                "timestamp": (timestamp or datetime.utcnow()).isoformat(),
            },
        )

    @classmethod
    def create_suggestion_node(cls, suggestion: Suggestion) -> "KnowledgeNode":
        """Create a suggestion node from a Suggestion value object."""
        return cls(
            id=KnowledgeNodeId.generate(),
            node_type=KnowledgeNodeType.SUGGESTION,
            label=suggestion.title,
            properties={
                "description": suggestion.description,
                "relevance_score": suggestion.relevance_score,
                "based_on": suggestion.based_on,
                "action_type": suggestion.action_type,
            },
        )

    @classmethod
    def create_entity_node(cls, entity: Entity) -> "KnowledgeNode":
        """Create an entity node from an Entity value object."""
        return cls(
            id=KnowledgeNodeId.generate(),
            node_type=KnowledgeNodeType.ENTITY,
            label=entity.value,
            properties={
                "entity_type": entity.entity_type.value,
                "context": entity.context,
                "confidence": entity.confidence,
                **entity.metadata,
            },
        )

    def update_properties(self, **kwargs: Any) -> "KnowledgeNode":
        """Update node properties."""
        new_properties = {**self.properties, **kwargs}
        return self.model_copy(
            update={
                "properties": new_properties,
                "updated_at": datetime.utcnow(),
            }
        )


class KnowledgeGraph(BaseModel):
    """Represents a user's knowledge graph with nodes and relationships."""

    user_id: UserId
    nodes: Annotated[dict[str, KnowledgeNode], Field(default_factory=dict)]
    relationships: Annotated[list[Relationship], Field(default_factory=list)]

    def add_node(self, node: KnowledgeNode) -> "KnowledgeGraph":
        """Add a node to the graph."""
        nodes = {**self.nodes, str(node.id): node}
        return self.model_copy(update={"nodes": nodes})

    def add_relationship(self, relationship: Relationship) -> "KnowledgeGraph":
        """Add a relationship to the graph."""
        relationships = [*self.relationships, relationship]
        return self.model_copy(update={"relationships": relationships})

    def connect_nodes(
        self,
        source_node: KnowledgeNode,
        target_node: KnowledgeNode,
        relation_type: RelationType,
        weight: float = 1.0,
        properties: dict[str, Any] | None = None,
    ) -> "KnowledgeGraph":
        """Connect two nodes with a relationship."""
        relationship = Relationship(
            relation_type=relation_type,
            source_id=str(source_node.id),
            target_id=str(target_node.id),
            weight=weight,
            properties=properties or {},
        )
        return self.add_relationship(relationship)

    def get_node(self, node_id: str) -> KnowledgeNode | None:
        """Get a node by ID."""
        return self.nodes.get(node_id)

    def get_nodes_by_type(self, node_type: KnowledgeNodeType) -> list[KnowledgeNode]:
        """Get all nodes of a specific type."""
        return [node for node in self.nodes.values() if node.node_type == node_type]

    def get_relationships_for_node(self, node_id: str) -> list[Relationship]:
        """Get all relationships involving a specific node."""
        return [
            rel for rel in self.relationships
            if rel.source_id == node_id or rel.target_id == node_id
        ]

    def get_connected_nodes(
        self,
        node_id: str,
        relation_type: RelationType | None = None,
    ) -> list[KnowledgeNode]:
        """Get nodes connected to a specific node."""
        connected_ids: set[str] = set()
        for rel in self.relationships:
            if relation_type and rel.relation_type != relation_type:
                continue
            if rel.source_id == node_id:
                connected_ids.add(rel.target_id)
            elif rel.target_id == node_id:
                connected_ids.add(rel.source_id)
        
        return [self.nodes[nid] for nid in connected_ids if nid in self.nodes]

    @property
    def node_count(self) -> int:
        """Get the number of nodes."""
        return len(self.nodes)

    @property
    def relationship_count(self) -> int:
        """Get the number of relationships."""
        return len(self.relationships)
