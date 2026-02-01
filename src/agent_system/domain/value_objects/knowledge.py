"""Knowledge graph value objects."""

from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, Field


class IntentType(str, Enum):
    """Type of user intent."""

    QUESTION = "question"
    TASK = "task"
    EXPLORATION = "exploration"
    CLARIFICATION = "clarification"
    FEEDBACK = "feedback"
    COMMAND = "command"
    META = "meta"  # When user asks about assistant capabilities/tools


class EntityType(str, Enum):
    """Type of extracted entity."""

    TOPIC = "topic"
    TOOL = "tool"
    CONCEPT = "concept"
    PERSON = "person"
    ORGANIZATION = "organization"
    LOCATION = "location"
    DATETIME = "datetime"
    CODE = "code"
    FILE = "file"
    URL = "url"


class RelationType(str, Enum):
    """Type of relationship between knowledge nodes."""

    # Structural relationships
    HAS_INTENT = "HAS_INTENT"
    INTERESTED_IN = "INTERESTED_IN"
    RELATES_TO = "RELATES_TO"
    USED_TOOL = "USED_TOOL"
    FOLLOWED_BY = "FOLLOWED_BY"
    SUGGESTS = "SUGGESTS"
    MENTIONED_IN = "MENTIONED_IN"
    DEPENDS_ON = "DEPENDS_ON"
    SIMILAR_TO = "SIMILAR_TO"
    
    # Semantic relationships for richer knowledge graphs
    LIKES = "LIKES"  # Subject likes/prefers something
    OWNS = "OWNS"  # Subject owns/has something
    LOCATED_IN = "LOCATED_IN"  # Entity is in a location
    IS_A = "IS_A"  # Type/category relationship
    HAS_ATTRIBUTE = "HAS_ATTRIBUTE"  # Entity has property
    ASSOCIATED_WITH = "ASSOCIATED_WITH"  # General association
    KNOWS = "KNOWS"  # User knows person/entity
    DISCUSSED = "DISCUSSED"  # User discussed topic
    BELONGS_TO = "BELONGS_TO"  # Membership relationship
    WORKS_AT = "WORKS_AT"  # Employment relationship
    LIVES_IN = "LIVES_IN"  # Residence relationship


class Intent(BaseModel):
    """Represents a user's intent extracted from interaction."""

    intent_type: IntentType
    description: str
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    entities: Annotated[list[str], Field(default_factory=list)]
    extracted_at: Annotated[datetime, Field(default_factory=datetime.utcnow)]

    def is_high_confidence(self) -> bool:
        """Check if intent has high confidence."""
        return self.confidence >= 0.8


class Entity(BaseModel):
    """Represents an extracted entity from conversation."""

    entity_type: EntityType
    value: str
    context: str | None = None
    confidence: Annotated[float, Field(ge=0.0, le=1.0, default=1.0)]
    metadata: Annotated[dict[str, Any], Field(default_factory=dict)]


class Relationship(BaseModel):
    """Represents a relationship between two knowledge nodes."""

    relation_type: RelationType
    source_id: str
    target_id: str
    weight: Annotated[float, Field(ge=0.0, le=1.0, default=1.0)]
    properties: Annotated[dict[str, Any], Field(default_factory=dict)]
    created_at: Annotated[datetime, Field(default_factory=datetime.utcnow)]


class Suggestion(BaseModel):
    """A proactive suggestion based on knowledge graph analysis."""

    title: str
    description: str
    relevance_score: Annotated[float, Field(ge=0.0, le=1.0)]
    based_on: list[str]  # IDs of knowledge nodes that informed this
    action_type: str | None = None  # e.g., "explore_topic", "use_tool", "follow_up"
    metadata: Annotated[dict[str, Any], Field(default_factory=dict)]

    def is_relevant(self, threshold: float = 0.5) -> bool:
        """Check if suggestion meets relevance threshold."""
        return self.relevance_score >= threshold
