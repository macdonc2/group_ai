"""Expertise Profiling Service - Tracks user expertise levels in topics."""

import logging
import os
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from agent_system.domain.value_objects import UserId
from agent_system.domain.value_objects.knowledge import ExpertiseLevel

logger = logging.getLogger(__name__)


class ExpertiseAssessment(BaseModel):
    """Result of expertise assessment by LLM."""
    
    topic: str = Field(description="The topic being assessed")
    level: str = Field(
        description="Expertise level: novice, beginner, intermediate, advanced, or expert"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence in this assessment"
    )
    evidence: str = Field(description="Evidence supporting this assessment")


EXPERTISE_PROMPT = """You are an expert at assessing a user's expertise level in various topics based on their messages.

Analyze the user's statement and determine their expertise level in the relevant topic.

Expertise Levels:
- NOVICE: Asking very basic questions, unfamiliar with terminology
- BEGINNER: Knows basics but asks many clarifying questions
- INTERMEDIATE: Comfortable with concepts, asks specific questions
- ADVANCED: Deep understanding, discusses nuances and edge cases
- EXPERT: Professional-level knowledge, may be teaching or advising

Indicators of expertise:
- Use of technical terminology (correctly vs incorrectly)
- Specificity of questions asked
- Assumptions made in statements
- Depth of context provided
- Ability to identify edge cases

Be conservative in your assessments. Most users are intermediate or below in most topics.
"""


def _get_model(api_key: str | None = None) -> OpenAIResponsesModel | str:
    """Get model for expertise assessment."""
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if key:
        return OpenAIResponsesModel("gpt-5-mini", provider=OpenAIProvider(api_key=key))
    return "openai:gpt-5-mini"


class ExpertiseProfiler:
    """Tracks and updates user expertise profiles.
    
    Analyzes user messages to build an understanding of their
    expertise level in various topics.
    """
    
    def __init__(
        self,
        knowledge_graph_port: Any,
        api_key: str | None = None,
    ):
        """Initialize the expertise profiler.
        
        Args:
            knowledge_graph_port: The Neo4j adapter
            api_key: Optional OpenAI API key
        """
        self.knowledge_graph = knowledge_graph_port
        self.api_key = api_key
        self._agent: Agent | None = None
    
    def _get_agent(self) -> Agent[None, ExpertiseAssessment]:
        """Get or create the assessment agent."""
        if not self._agent:
            self._agent = Agent(
                _get_model(self.api_key),
                output_type=ExpertiseAssessment,
                system_prompt=EXPERTISE_PROMPT,
            )
        return self._agent
    
    async def assess_expertise(
        self,
        message: str,
        topic: str | None = None,
    ) -> ExpertiseAssessment:
        """Assess expertise level from a user message.
        
        Args:
            message: The user's message
            topic: Optional explicit topic to assess
            
        Returns:
            ExpertiseAssessment with level and confidence
        """
        prompt = f"""Analyze this user message and determine their expertise level:

Message: "{message}"

{f'Focus on the topic: {topic}' if topic else 'Identify the main topic and assess expertise in it.'}

Provide:
1. The topic being discussed
2. The expertise level (novice/beginner/intermediate/advanced/expert)
3. Your confidence in this assessment
4. Evidence from the message that supports your assessment"""

        try:
            agent = self._get_agent()
            result = await agent.run(prompt)
            return result.output
        except Exception as e:
            logger.error(f"Expertise assessment failed: {e}")
            return ExpertiseAssessment(
                topic=topic or "unknown",
                level="intermediate",  # Safe default
                confidence=0.3,
                evidence=f"Could not assess: {str(e)}",
            )
    
    def _level_to_enum(self, level: str) -> ExpertiseLevel:
        """Convert string level to ExpertiseLevel enum."""
        level_map = {
            "novice": ExpertiseLevel.NOVICE,
            "beginner": ExpertiseLevel.BEGINNER,
            "intermediate": ExpertiseLevel.INTERMEDIATE,
            "advanced": ExpertiseLevel.ADVANCED,
            "expert": ExpertiseLevel.EXPERT,
        }
        return level_map.get(level.lower(), ExpertiseLevel.INTERMEDIATE)
    
    async def update_user_expertise(
        self,
        user_id: UserId,
        message: str,
    ) -> list[dict[str, Any]]:
        """Update user's expertise profile based on a message.
        
        Args:
            user_id: The user's ID
            message: The user's message
            
        Returns:
            List of expertise updates made
        """
        updates = []
        
        # Assess expertise from the message
        assessment = await self.assess_expertise(message)
        
        if assessment.confidence < 0.5:
            return updates  # Not confident enough
        
        # Store the expertise assessment
        # For now, store as a preference with the topic
        try:
            await self.knowledge_graph.store_preference(
                user_id=user_id,
                category="expertise",
                value=f"{assessment.topic}: {assessment.level}",
                sentiment=self._level_to_score(assessment.level),
                subcategory=assessment.topic,
            )
            
            updates.append({
                "topic": assessment.topic,
                "level": assessment.level,
                "confidence": assessment.confidence,
            })
            
            logger.debug(
                f"Updated expertise for {assessment.topic}: "
                f"{assessment.level} (confidence: {assessment.confidence:.0%})"
            )
        except Exception as e:
            logger.error(f"Failed to store expertise update: {e}")
        
        return updates
    
    def _level_to_score(self, level: str) -> float:
        """Convert expertise level to a numeric score."""
        scores = {
            "novice": 0.1,
            "beginner": 0.3,
            "intermediate": 0.5,
            "advanced": 0.7,
            "expert": 0.9,
        }
        return scores.get(level.lower(), 0.5)
    
    async def get_user_expertise(
        self,
        user_id: UserId,
        topic: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get user's expertise profile.
        
        Args:
            user_id: The user's ID
            topic: Optional specific topic to query
            
        Returns:
            List of expertise entries
        """
        try:
            prefs = await self.knowledge_graph.get_user_preferences(
                user_id=user_id,
                category="expertise",
                min_confidence=0.0,
            )
            
            expertise = []
            for pref in prefs:
                value = pref.get("value", "")
                if ": " in value:
                    topic_name, level = value.split(": ", 1)
                    if topic is None or topic.lower() in topic_name.lower():
                        expertise.append({
                            "topic": topic_name,
                            "level": level,
                            "confidence": pref.get("confidence", 0.5),
                            "mention_count": pref.get("mention_count", 1),
                        })
            
            return expertise
        except Exception as e:
            logger.error(f"Failed to get user expertise: {e}")
            return []
    
    async def get_response_detail_level(
        self,
        user_id: UserId,
        topic: str,
    ) -> str:
        """Determine appropriate response detail level for a topic.
        
        Args:
            user_id: The user's ID
            topic: The topic being discussed
            
        Returns:
            Response style guidance: "detailed", "standard", or "concise"
        """
        expertise = await self.get_user_expertise(user_id, topic)
        
        if not expertise:
            return "standard"
        
        # Get the highest confidence expertise for this topic
        relevant = sorted(expertise, key=lambda x: x.get("confidence", 0), reverse=True)
        if not relevant:
            return "standard"
        
        level = relevant[0].get("level", "intermediate").lower()
        
        if level in ["novice", "beginner"]:
            return "detailed"  # More explanation needed
        elif level in ["advanced", "expert"]:
            return "concise"  # Skip basics, be direct
        else:
            return "standard"
