"""Multi-hop Inference Engine - Derives new knowledge through graph traversal."""

import logging
from typing import Any

from agent_system.domain.value_objects import UserId

logger = logging.getLogger(__name__)


class InferenceRule:
    """A rule for deriving new knowledge from existing facts."""
    
    def __init__(
        self,
        name: str,
        description: str,
        pattern: str,
        conclusion: str,
        confidence_decay: float = 0.9,
    ):
        """Initialize an inference rule.
        
        Args:
            name: Name of the rule
            description: Human-readable description
            pattern: Cypher pattern to match (e.g., "(a)-[:LIKES]->(b)-[:IS_A]->(c)")
            conclusion: New relationship to create
            confidence_decay: Multiplier for derived confidence (each hop reduces confidence)
        """
        self.name = name
        self.description = description
        self.pattern = pattern
        self.conclusion = conclusion
        self.confidence_decay = confidence_decay


# Default inference rules
DEFAULT_RULES = [
    InferenceRule(
        name="category_preference",
        description="If user likes X and X is-a Category, then user likes Category",
        pattern="(u:KnowledgeNode)-[:LIKES]->(item)-[:IS_A]->(cat)",
        conclusion="LIKES",
    ),
    InferenceRule(
        name="pet_food_category",
        description="If pet likes Food and Food is-a Category, then pet likes Category",
        pattern="(p:PetNode)-[:LIKES]->(food)-[:IS_A]->(cat)",
        conclusion="LIKES",
    ),
    InferenceRule(
        name="location_via_person",
        description="If user knows Person and Person works-at Location, user might know Location",
        pattern="(u:KnowledgeNode)-[:KNOWS]->(p:PersonNode)-[:WORKS_AT]->(l:LocationNode)",
        conclusion="ASSOCIATED_WITH",
    ),
    InferenceRule(
        name="friend_of_friend",
        description="Friends of friends might be acquaintances",
        pattern="(u:KnowledgeNode)-[:KNOWS]->(p1:PersonNode)-[:FRIEND_OF]->(p2:PersonNode)",
        conclusion="ACQUAINTANCE",
    ),
]


class InferenceEngine:
    """Engine for deriving new knowledge through multi-hop graph reasoning.
    
    Uses predefined rules to traverse the knowledge graph and infer
    new relationships that aren't explicitly stated.
    """
    
    def __init__(
        self,
        knowledge_graph_port: Any,
        rules: list[InferenceRule] | None = None,
    ):
        """Initialize the inference engine.
        
        Args:
            knowledge_graph_port: The Neo4j adapter
            rules: Custom inference rules (defaults to DEFAULT_RULES)
        """
        self.knowledge_graph = knowledge_graph_port
        self.rules = rules or DEFAULT_RULES
        self._cache: dict[str, list[dict]] = {}
    
    async def infer(
        self,
        user_id: UserId,
        max_depth: int = 2,
        cache_ttl: int = 300,
    ) -> list[dict[str, Any]]:
        """Run all inference rules and return derived facts.
        
        Args:
            user_id: The user to infer for
            max_depth: Maximum traversal depth
            cache_ttl: Cache time-to-live in seconds
            
        Returns:
            List of inferred facts with confidence scores
        """
        inferences = []
        
        for rule in self.rules:
            try:
                rule_inferences = await self._apply_rule(
                    user_id=user_id,
                    rule=rule,
                    max_depth=max_depth,
                )
                inferences.extend(rule_inferences)
            except Exception as e:
                logger.error(f"Rule '{rule.name}' failed: {e}")
        
        return inferences
    
    async def _apply_rule(
        self,
        user_id: UserId,
        rule: InferenceRule,
        max_depth: int,
    ) -> list[dict[str, Any]]:
        """Apply a single inference rule.
        
        Args:
            user_id: The user to infer for
            rule: The rule to apply
            max_depth: Maximum traversal depth
            
        Returns:
            List of inferred facts from this rule
        """
        inferences = []
        
        # For now, implement basic multi-hop traversal
        # In a full implementation, we would parse the Cypher pattern
        # and execute it against Neo4j
        
        try:
            # Get user's direct connections
            user_nodes = await self.knowledge_graph.get_user_nodes(
                user_id=user_id,
                node_type=None,
            )
            
            for node in user_nodes:
                # Get 2-hop connections
                connected = await self.knowledge_graph.find_connected_nodes(
                    node_id=node.id,
                    max_depth=max_depth,
                )
                
                for conn in connected:
                    # Check if this connection matches the rule pattern
                    # This is a simplified implementation
                    if self._matches_pattern(node, conn, rule):
                        inference = {
                            "rule": rule.name,
                            "source": node.label,
                            "target": conn.label,
                            "relationship": rule.conclusion,
                            "confidence": 0.8 * (rule.confidence_decay ** max_depth),
                            "explanation": f"Inferred via {rule.description}",
                        }
                        inferences.append(inference)
        
        except Exception as e:
            logger.debug(f"Multi-hop inference failed: {e}")
        
        return inferences
    
    def _matches_pattern(
        self,
        source: Any,
        target: Any,
        rule: InferenceRule,
    ) -> bool:
        """Check if a source-target pair matches a rule pattern.
        
        This is a simplified pattern matcher. A full implementation
        would parse Cypher patterns.
        """
        # Simple type-based matching
        source_type = getattr(source, "node_type", None)
        target_type = getattr(target, "node_type", None)
        
        if not source_type or not target_type:
            return False
        
        # Match based on rule name heuristics
        if rule.name == "category_preference":
            return source_type.value == "topic" and target_type.value == "topic"
        elif rule.name == "location_via_person":
            return source_type.value == "person" and target_type.value == "location"
        
        return False
    
    async def get_inferred_preferences(
        self,
        user_id: UserId,
    ) -> list[dict[str, Any]]:
        """Get preferences inferred from the knowledge graph.
        
        This analyzes patterns in the user's interests and interactions
        to suggest preferences they haven't explicitly stated.
        
        Args:
            user_id: The user's ID
            
        Returns:
            List of inferred preferences
        """
        inferences = await self.infer(user_id, max_depth=2)
        
        # Filter to preference-like inferences
        preferences = [
            inf for inf in inferences
            if inf.get("relationship") in ["LIKES", "PREFERS", "INTERESTED_IN"]
        ]
        
        return preferences
    
    async def explain_connection(
        self,
        user_id: UserId,
        entity_name: str,
    ) -> dict[str, Any]:
        """Explain how an entity is connected to the user.
        
        Traces the path from the user to the entity in the graph.
        
        Args:
            user_id: The user's ID
            entity_name: Name of the entity to explain
            
        Returns:
            Dict with connection path and explanation
        """
        try:
            # Resolve the entity
            entity = await self.knowledge_graph.resolve_entity_by_alias(
                user_id=user_id,
                alias=entity_name,
            )
            
            if not entity:
                return {
                    "connected": False,
                    "entity": entity_name,
                    "explanation": f"No direct connection found to '{entity_name}'",
                }
            
            # Get relationships
            relationships = await self.knowledge_graph.get_entity_relationships(
                user_id=user_id,
                entity_type=entity["type"],
                entity_name=entity["entity"].get("name", entity_name),
                max_depth=3,
            )
            
            if not relationships:
                return {
                    "connected": True,
                    "entity": entity_name,
                    "type": entity["type"],
                    "explanation": f"You know {entity_name} directly.",
                    "path": ["you", entity_name],
                }
            
            # Build explanation from relationships
            paths = []
            for rel in relationships[:3]:
                path = " → ".join(rel.get("relationship_path", []))
                paths.append(f"{entity_name} {path} {rel.get('related_name', 'unknown')}")
            
            return {
                "connected": True,
                "entity": entity_name,
                "type": entity["type"],
                "explanation": f"Connected to {entity_name} via: {'; '.join(paths)}",
                "relationships": relationships[:5],
            }
        
        except Exception as e:
            logger.error(f"Failed to explain connection: {e}")
            return {
                "connected": False,
                "entity": entity_name,
                "explanation": f"Could not determine connection: {str(e)}",
            }
    
    async def suggest_related(
        self,
        user_id: UserId,
        entity_name: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Suggest entities related to a given entity.
        
        Uses multi-hop traversal to find entities connected
        to the given entity in the knowledge graph.
        
        Args:
            user_id: The user's ID
            entity_name: Name of the entity to find relations for
            limit: Maximum suggestions to return
            
        Returns:
            List of related entity suggestions
        """
        suggestions = []
        
        try:
            # Get relationships for the entity
            relationships = await self.knowledge_graph.get_entity_relationships(
                user_id=user_id,
                entity_type="person",  # Start with person, fall back
                entity_name=entity_name,
                max_depth=2,
            )
            
            # Also try other entity types
            for entity_type in ["pet", "location"]:
                more_rels = await self.knowledge_graph.get_entity_relationships(
                    user_id=user_id,
                    entity_type=entity_type,
                    entity_name=entity_name,
                    max_depth=2,
                )
                relationships.extend(more_rels)
            
            # Convert to suggestions
            seen = set()
            for rel in relationships:
                name = rel.get("related_name")
                if name and name not in seen:
                    seen.add(name)
                    suggestions.append({
                        "name": name,
                        "type": rel.get("related_type", "unknown"),
                        "relationship": " → ".join(rel.get("relationship_path", [])),
                        "depth": rel.get("depth", 1),
                    })
                    
                    if len(suggestions) >= limit:
                        break
        
        except Exception as e:
            logger.error(f"Failed to suggest related: {e}")
        
        return suggestions
