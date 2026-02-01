"""Knowledge graph-related domain events."""

from agent_system.domain.entities import KnowledgeNodeType
from agent_system.domain.events.base import DomainEvent
from agent_system.domain.value_objects import KnowledgeNodeId, RelationType, UserId


class KnowledgeNodeCreated(DomainEvent):
    """Event raised when a knowledge node is created."""

    node_id: KnowledgeNodeId
    user_id: UserId
    node_type: KnowledgeNodeType
    label: str


class RelationshipCreated(DomainEvent):
    """Event raised when a relationship is created."""

    source_id: KnowledgeNodeId
    target_id: KnowledgeNodeId
    relation_type: RelationType
    user_id: UserId


class IntentExtracted(DomainEvent):
    """Event raised when an intent is extracted from conversation."""

    user_id: UserId
    conversation_id: str
    intent_type: str
    description: str
    confidence: float


class SuggestionGenerated(DomainEvent):
    """Event raised when a suggestion is generated."""

    user_id: UserId
    suggestion_title: str
    relevance_score: float
    based_on_nodes: list[str]
