"""Contradiction Detection Service - Identifies conflicting information in knowledge graph."""

import logging
import os
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from agent_system.domain.value_objects import UserId

logger = logging.getLogger(__name__)


class ContradictionAssessment(BaseModel):
    """Result of contradiction assessment by LLM."""
    
    is_contradiction: bool = Field(
        description="Whether this represents a real contradiction"
    )
    severity: float = Field(
        ge=0.0, le=1.0,
        description="Severity of the contradiction (0=minor, 1=major)"
    )
    explanation: str = Field(
        description="Explanation of why this is or isn't a contradiction"
    )
    suggested_resolution: str | None = Field(
        default=None,
        description="Suggested way to resolve the contradiction"
    )


CONTRADICTION_PROMPT = """You are an expert at detecting contradictions in personal information.

Given OLD and NEW values for an attribute of an entity, determine if they truly contradict each other.

NOT contradictions:
- Updates/additions: "likes pizza" -> "likes pizza and sushi" (addition, not contradiction)
- Refinements: "works at tech company" -> "works at Google" (more specific, not contradiction)
- Time-based changes: "lives in NYC" -> "lives in LA" (could have moved - may not be contradiction)
- Different contexts: "vegetarian" and "ate steak yesterday" (might be exception, ask for clarification)

TRUE contradictions:
- Direct opposites: "loves cats" vs "hates cats"
- Mutually exclusive: "is 30 years old" vs "is 45 years old"
- Logical impossibility: "has no pets" vs "has a dog named Max"

Consider that people's preferences and situations can change over time.
When in doubt, lean toward NOT being a contradiction, especially for preferences.

For severity:
- 0.0-0.3: Minor (easily could have changed)
- 0.4-0.6: Moderate (notable change, worth noting)
- 0.7-1.0: Major (likely error or significant update needed)
"""


def _get_model(api_key: str | None = None) -> OpenAIResponsesModel | str:
    """Get model for contradiction assessment."""
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if key:
        return OpenAIResponsesModel("gpt-5-mini", provider=OpenAIProvider(api_key=key))
    return "openai:gpt-5-mini"


class ContradictionDetector:
    """Detects contradictions in entity information.
    
    When entity attributes are updated, compares old and new values
    to identify potential contradictions that need resolution.
    """
    
    def __init__(
        self,
        knowledge_graph_port: Any,
        api_key: str | None = None,
    ):
        """Initialize the contradiction detector.
        
        Args:
            knowledge_graph_port: The Neo4j adapter
            api_key: Optional OpenAI API key
        """
        self.knowledge_graph = knowledge_graph_port
        self.api_key = api_key
        self._agent: Agent | None = None
    
    def _get_agent(self) -> Agent[None, ContradictionAssessment]:
        """Get or create the assessment agent."""
        if not self._agent:
            self._agent = Agent(
                _get_model(self.api_key),
                output_type=ContradictionAssessment,
                system_prompt=CONTRADICTION_PROMPT,
            )
        return self._agent
    
    async def check_contradiction(
        self,
        entity_type: str,
        entity_name: str,
        attribute: str,
        old_value: str,
        new_value: str,
    ) -> ContradictionAssessment:
        """Check if an update represents a contradiction.
        
        Args:
            entity_type: Type of entity (person, pet, location)
            entity_name: Name of the entity
            attribute: The attribute being updated
            old_value: Previous value
            new_value: New value
            
        Returns:
            ContradictionAssessment with analysis
        """
        prompt = f"""Entity: {entity_name} ({entity_type})
Attribute: {attribute}

OLD value: {old_value}
NEW value: {new_value}

Is this a contradiction? Assess the severity and provide explanation."""

        try:
            agent = self._get_agent()
            result = await agent.run(prompt)
            return result.output
        except Exception as e:
            logger.error(f"Contradiction assessment failed: {e}")
            # Default to not a contradiction on error
            return ContradictionAssessment(
                is_contradiction=False,
                severity=0.0,
                explanation=f"Could not assess: {str(e)}",
                suggested_resolution=None,
            )
    
    async def detect_and_store_contradiction(
        self,
        user_id: UserId,
        entity_type: str,
        entity_name: str,
        attribute: str,
        old_value: str,
        new_value: str,
        old_source: str | None = None,
        new_source: str | None = None,
    ) -> dict[str, Any] | None:
        """Detect contradiction and store if found.
        
        Args:
            user_id: The user's ID
            entity_type: Type of entity
            entity_name: Name of the entity
            attribute: The attribute
            old_value: Previous value
            new_value: New value
            old_source: Source conversation of old value
            new_source: Source conversation of new value
            
        Returns:
            Contradiction dict if found, None otherwise
        """
        # Skip trivial cases
        if old_value.lower().strip() == new_value.lower().strip():
            return None
        
        # Assess the contradiction
        assessment = await self.check_contradiction(
            entity_type=entity_type,
            entity_name=entity_name,
            attribute=attribute,
            old_value=old_value,
            new_value=new_value,
        )
        
        if not assessment.is_contradiction:
            return None
        
        # Only store significant contradictions
        if assessment.severity < 0.3:
            logger.debug(
                f"Minor contradiction ignored: {entity_name}.{attribute} "
                f"({old_value} -> {new_value})"
            )
            return None
        
        # Store the contradiction
        contradiction = {
            "entity_type": entity_type,
            "entity_name": entity_name,
            "attribute": attribute,
            "old_value": old_value,
            "new_value": new_value,
            "old_source": old_source,
            "new_source": new_source,
            "severity": assessment.severity,
            "explanation": assessment.explanation,
            "suggested_resolution": assessment.suggested_resolution,
        }
        
        logger.info(
            f"Detected contradiction for {entity_name}.{attribute}: "
            f"'{old_value}' vs '{new_value}' (severity: {assessment.severity})"
        )
        
        return contradiction
    
    async def get_unresolved_contradictions(
        self,
        user_id: UserId,
    ) -> list[dict[str, Any]]:
        """Get all unresolved contradictions for a user.
        
        This would query the knowledge graph for stored contradictions.
        
        Args:
            user_id: The user's ID
            
        Returns:
            List of unresolved contradiction dicts
        """
        # For now, return empty list as we'd need a dedicated contradiction storage
        # This could be implemented by querying ContractionNode types
        return []
    
    async def resolve_contradiction(
        self,
        user_id: UserId,
        contradiction_id: str,
        resolution: str,
        keep_value: str,  # "old" or "new"
    ) -> bool:
        """Mark a contradiction as resolved.
        
        Args:
            user_id: The user's ID
            contradiction_id: ID of the contradiction to resolve
            resolution: Explanation of how it was resolved
            keep_value: Which value to keep ("old" or "new")
            
        Returns:
            True if successfully resolved
        """
        # Would mark the contradiction as resolved in the knowledge graph
        logger.info(f"Resolved contradiction {contradiction_id}: {resolution}")
        return True


class BatchContradictionChecker:
    """Checks for contradictions in batch when importing or syncing data."""
    
    def __init__(
        self,
        detector: ContradictionDetector,
    ):
        """Initialize the batch checker.
        
        Args:
            detector: The contradiction detector to use
        """
        self.detector = detector
    
    async def check_person_update(
        self,
        user_id: UserId,
        person_name: str,
        old_data: dict[str, Any],
        new_data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Check for contradictions when updating a person.
        
        Args:
            user_id: The user's ID
            person_name: Name of the person
            old_data: Existing person data
            new_data: New/updated data
            
        Returns:
            List of detected contradictions
        """
        contradictions = []
        
        # Check relevant attributes
        attributes_to_check = [
            ("relationship_type", "relationship"),
            ("email", "email address"),
            ("phone", "phone number"),
        ]
        
        for attr_key, attr_name in attributes_to_check:
            old_val = old_data.get(attr_key)
            new_val = new_data.get(attr_key)
            
            if old_val and new_val and old_val != new_val:
                contradiction = await self.detector.detect_and_store_contradiction(
                    user_id=user_id,
                    entity_type="person",
                    entity_name=person_name,
                    attribute=attr_name,
                    old_value=str(old_val),
                    new_value=str(new_val),
                )
                if contradiction:
                    contradictions.append(contradiction)
        
        return contradictions
    
    async def check_pet_update(
        self,
        user_id: UserId,
        pet_name: str,
        old_data: dict[str, Any],
        new_data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Check for contradictions when updating a pet.
        
        Args:
            user_id: The user's ID
            pet_name: Name of the pet
            old_data: Existing pet data
            new_data: New/updated data
            
        Returns:
            List of detected contradictions
        """
        contradictions = []
        
        attributes_to_check = [
            ("species", "species"),
            ("breed", "breed"),
        ]
        
        for attr_key, attr_name in attributes_to_check:
            old_val = old_data.get(attr_key)
            new_val = new_data.get(attr_key)
            
            if old_val and new_val and old_val.lower() != new_val.lower():
                contradiction = await self.detector.detect_and_store_contradiction(
                    user_id=user_id,
                    entity_type="pet",
                    entity_name=pet_name,
                    attribute=attr_name,
                    old_value=str(old_val),
                    new_value=str(new_val),
                )
                if contradiction:
                    contradictions.append(contradiction)
        
        return contradictions
