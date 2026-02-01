"""Knowledge graph port interface for Neo4j interactions."""

from abc import ABC, abstractmethod
from typing import Any

from agent_system.domain.entities import KnowledgeNode, KnowledgeNodeType
from agent_system.domain.value_objects import (
    KnowledgeNodeId,
    Relationship,
    RelationType,
    Suggestion,
    UserId,
)


class KnowledgeGraphPort(ABC):
    """Port interface for knowledge graph operations."""

    @abstractmethod
    async def create_node(self, node: KnowledgeNode) -> KnowledgeNode:
        """Create a new node in the graph.
        
        Args:
            node: The knowledge node to create
            
        Returns:
            The created node with any server-side updates
        """
        ...

    @abstractmethod
    async def get_node(self, node_id: KnowledgeNodeId) -> KnowledgeNode | None:
        """Get a node by ID.
        
        Args:
            node_id: The node identifier
            
        Returns:
            The node if found, None otherwise
        """
        ...

    @abstractmethod
    async def update_node(self, node: KnowledgeNode) -> KnowledgeNode:
        """Update an existing node.
        
        Args:
            node: The node with updated properties
            
        Returns:
            The updated node
        """
        ...

    @abstractmethod
    async def delete_node(self, node_id: KnowledgeNodeId) -> bool:
        """Delete a node and its relationships.
        
        Args:
            node_id: The node identifier
            
        Returns:
            True if deleted, False if not found
        """
        ...

    @abstractmethod
    async def create_relationship(
        self,
        source_id: KnowledgeNodeId,
        target_id: KnowledgeNodeId,
        relation_type: RelationType,
        properties: dict[str, Any] | None = None,
    ) -> Relationship:
        """Create a relationship between two nodes.
        
        Args:
            source_id: Source node ID
            target_id: Target node ID
            relation_type: Type of relationship
            properties: Optional relationship properties
            
        Returns:
            The created relationship
        """
        ...

    @abstractmethod
    async def get_relationships(
        self,
        node_id: KnowledgeNodeId,
        relation_type: RelationType | None = None,
        direction: str = "both",  # "outgoing", "incoming", "both"
    ) -> list[Relationship]:
        """Get relationships for a node.
        
        Args:
            node_id: The node identifier
            relation_type: Optional filter by relationship type
            direction: Direction of relationships to return
            
        Returns:
            List of relationships
        """
        ...

    @abstractmethod
    async def find_nodes(
        self,
        node_type: KnowledgeNodeType | None = None,
        properties: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> list[KnowledgeNode]:
        """Find nodes matching criteria.
        
        Args:
            node_type: Optional filter by node type
            properties: Optional filter by properties
            limit: Maximum number of results
            
        Returns:
            List of matching nodes
        """
        ...

    @abstractmethod
    async def get_user_nodes(
        self,
        user_id: UserId,
        node_type: KnowledgeNodeType | None = None,
    ) -> list[KnowledgeNode]:
        """Get all nodes associated with a user.
        
        Args:
            user_id: The user identifier
            node_type: Optional filter by node type
            
        Returns:
            List of user's nodes
        """
        ...

    @abstractmethod
    async def find_connected_nodes(
        self,
        node_id: KnowledgeNodeId,
        relation_type: RelationType | None = None,
        max_depth: int = 1,
    ) -> list[KnowledgeNode]:
        """Find nodes connected to a given node.
        
        Args:
            node_id: Starting node ID
            relation_type: Optional filter by relationship type
            max_depth: Maximum traversal depth
            
        Returns:
            List of connected nodes
        """
        ...

    @abstractmethod
    async def get_suggestions_for_user(
        self,
        user_id: UserId,
        limit: int = 5,
    ) -> list[Suggestion]:
        """Get suggestions for a user based on their knowledge graph.
        
        Args:
            user_id: The user identifier
            limit: Maximum number of suggestions
            
        Returns:
            List of relevant suggestions
        """
        ...

    @abstractmethod
    async def record_interaction(
        self,
        user_id: UserId,
        conversation_id: str,
        summary: str,
        intents: list[str],
        entities: list[str],
        tools_used: list[str],
        user_label: str | None = None,
    ) -> KnowledgeNode:
        """Record an interaction in the knowledge graph.
        
        Creates an interaction node and connects it to relevant
        user, intent, entity, and tool nodes.
        
        Args:
            user_id: The user identifier
            conversation_id: The conversation identifier
            summary: Summary of the interaction
            intents: Extracted intent labels
            entities: Extracted entity values
            tools_used: Names of tools used
            user_label: Human-readable label for user node (e.g., email)
            
        Returns:
            The created interaction node
        """
        ...

    @abstractmethod
    async def clear_user_graph(self, user_id: UserId) -> int:
        """Clear all nodes and relationships for a user.
        
        Args:
            user_id: The user identifier
            
        Returns:
            Number of nodes deleted
        """
        ...

    @abstractmethod
    async def update_user_label(self, user_id: UserId, label: str) -> bool:
        """Update the label of a user node.
        
        Args:
            user_id: The user identifier
            label: The new label (e.g., email address)
            
        Returns:
            True if updated, False if node not found
        """
        ...

    # ============ Vector/Embedding Operations ============

    @abstractmethod
    async def ensure_vector_index(self, dimensions: int = 1536) -> bool:
        """Ensure the vector index exists for semantic search.
        
        Args:
            dimensions: Number of dimensions for the embeddings
            
        Returns:
            True if index exists or was created
        """
        ...

    @abstractmethod
    async def store_message_embedding(
        self,
        user_id: UserId,
        conversation_id: str,
        message_id: str,
        content: str,
        role: str,
        embedding: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store a message with its embedding for semantic search.
        
        Args:
            user_id: The user identifier
            conversation_id: The conversation identifier
            message_id: Unique message identifier
            content: The message content
            role: Message role (user/assistant)
            embedding: The embedding vector
            metadata: Optional additional metadata
            
        Returns:
            The node ID of the stored message
        """
        ...

    @abstractmethod
    async def semantic_search(
        self,
        user_id: UserId,
        query_embedding: list[float],
        limit: int = 10,
        min_score: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Search for semantically similar messages.
        
        Args:
            user_id: The user identifier
            query_embedding: The query embedding vector
            limit: Maximum number of results
            min_score: Minimum similarity score (0-1)
            
        Returns:
            List of matching messages with scores
        """
        ...
