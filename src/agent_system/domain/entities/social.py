"""Social graph entities - People, Pets, Locations tracked in the knowledge graph."""

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field

from agent_system.domain.value_objects import KnowledgeNodeId
from agent_system.domain.value_objects.knowledge import (
    ExpertiseLevel,
    LocationType,
    PatternType,
    PersonRelationType,
)


class Person(BaseModel):
    """Represents a person in the user's social graph."""

    id: KnowledgeNodeId
    name: str
    aliases: Annotated[list[str], Field(default_factory=list)]
    relationship_type: PersonRelationType | None = None
    context_notes: str | None = None
    email: str | None = None
    phone: str | None = None
    first_mentioned: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    last_mentioned: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    mention_count: int = 1
    metadata: Annotated[dict[str, Any], Field(default_factory=dict)]

    @classmethod
    def create(
        cls,
        name: str,
        relationship_type: PersonRelationType | None = None,
        aliases: list[str] | None = None,
        context_notes: str | None = None,
    ) -> "Person":
        """Create a new Person."""
        return cls(
            id=KnowledgeNodeId.generate(),
            name=name,
            aliases=aliases or [],
            relationship_type=relationship_type,
            context_notes=context_notes,
        )

    def update_mention(self) -> "Person":
        """Update last mention timestamp and increment count."""
        return self.model_copy(
            update={
                "last_mentioned": datetime.utcnow(),
                "mention_count": self.mention_count + 1,
            }
        )

    def add_alias(self, alias: str) -> "Person":
        """Add an alias for this person."""
        if alias.lower() not in [a.lower() for a in self.aliases]:
            return self.model_copy(update={"aliases": [*self.aliases, alias]})
        return self

    def matches_name_or_alias(self, query: str) -> bool:
        """Check if query matches name or any alias (case-insensitive)."""
        query_lower = query.lower()
        if query_lower == self.name.lower():
            return True
        return any(query_lower == alias.lower() for alias in self.aliases)


class Pet(BaseModel):
    """Represents a pet in the user's household."""

    id: KnowledgeNodeId
    name: str
    aliases: Annotated[list[str], Field(default_factory=list)]
    species: str | None = None  # dog, cat, bird, fish, etc.
    breed: str | None = None
    age: int | None = None
    personality: Annotated[list[str], Field(default_factory=list)]  # playful, lazy, etc.
    food_preferences: Annotated[list[str], Field(default_factory=list)]
    health_notes: str | None = None
    first_mentioned: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    last_mentioned: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    mention_count: int = 1
    metadata: Annotated[dict[str, Any], Field(default_factory=dict)]

    @classmethod
    def create(
        cls,
        name: str,
        species: str | None = None,
        breed: str | None = None,
        aliases: list[str] | None = None,
    ) -> "Pet":
        """Create a new Pet."""
        return cls(
            id=KnowledgeNodeId.generate(),
            name=name,
            species=species,
            breed=breed,
            aliases=aliases or [],
        )

    def update_mention(self) -> "Pet":
        """Update last mention timestamp and increment count."""
        return self.model_copy(
            update={
                "last_mentioned": datetime.utcnow(),
                "mention_count": self.mention_count + 1,
            }
        )

    def add_trait(self, trait: str) -> "Pet":
        """Add a personality trait."""
        if trait.lower() not in [t.lower() for t in self.personality]:
            return self.model_copy(update={"personality": [*self.personality, trait]})
        return self

    def add_food_preference(self, food: str) -> "Pet":
        """Add a food preference."""
        if food.lower() not in [f.lower() for f in self.food_preferences]:
            return self.model_copy(
                update={"food_preferences": [*self.food_preferences, food]}
            )
        return self

    def matches_name_or_alias(self, query: str) -> bool:
        """Check if query matches name or any alias (case-insensitive)."""
        query_lower = query.lower()
        if query_lower == self.name.lower():
            return True
        return any(query_lower == alias.lower() for alias in self.aliases)


class Location(BaseModel):
    """Represents a location the user frequents or mentions."""

    id: KnowledgeNodeId
    name: str
    aliases: Annotated[list[str], Field(default_factory=list)]
    location_type: LocationType | None = None
    address: str | None = None
    city: str | None = None
    neighborhood: str | None = None
    associated_activities: Annotated[list[str], Field(default_factory=list)]
    associated_people: Annotated[list[str], Field(default_factory=list)]  # Person IDs
    notes: str | None = None
    first_mentioned: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    last_mentioned: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    mention_count: int = 1
    metadata: Annotated[dict[str, Any], Field(default_factory=dict)]

    @classmethod
    def create(
        cls,
        name: str,
        location_type: LocationType | None = None,
        address: str | None = None,
        city: str | None = None,
        aliases: list[str] | None = None,
    ) -> "Location":
        """Create a new Location."""
        return cls(
            id=KnowledgeNodeId.generate(),
            name=name,
            location_type=location_type,
            address=address,
            city=city,
            aliases=aliases or [],
        )

    def update_mention(self) -> "Location":
        """Update last mention timestamp and increment count."""
        return self.model_copy(
            update={
                "last_mentioned": datetime.utcnow(),
                "mention_count": self.mention_count + 1,
            }
        )

    def add_activity(self, activity: str) -> "Location":
        """Add an associated activity."""
        if activity.lower() not in [a.lower() for a in self.associated_activities]:
            return self.model_copy(
                update={"associated_activities": [*self.associated_activities, activity]}
            )
        return self

    def matches_name_or_alias(self, query: str) -> bool:
        """Check if query matches name or any alias (case-insensitive)."""
        query_lower = query.lower()
        if query_lower in self.name.lower():
            return True
        return any(query_lower in alias.lower() for alias in self.aliases)


class Pattern(BaseModel):
    """Represents a detected behavioral pattern."""

    id: KnowledgeNodeId
    pattern_type: PatternType
    description: str
    frequency: str | None = None  # e.g., "every 4-5 hours", "weekly on Saturday"
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5
    occurrence_count: int = 0
    last_occurrence: datetime | None = None
    next_expected: datetime | None = None
    related_topics: Annotated[list[str], Field(default_factory=list)]
    created_at: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    metadata: Annotated[dict[str, Any], Field(default_factory=dict)]

    @classmethod
    def create(
        cls,
        pattern_type: PatternType,
        description: str,
        frequency: str | None = None,
        confidence: float = 0.5,
    ) -> "Pattern":
        """Create a new Pattern."""
        return cls(
            id=KnowledgeNodeId.generate(),
            pattern_type=pattern_type,
            description=description,
            frequency=frequency,
            confidence=confidence,
        )

    def record_occurrence(self) -> "Pattern":
        """Record an occurrence of this pattern."""
        return self.model_copy(
            update={
                "occurrence_count": self.occurrence_count + 1,
                "last_occurrence": datetime.utcnow(),
            }
        )


class Thread(BaseModel):
    """Represents a cross-conversation thread/project."""

    id: KnowledgeNodeId
    name: str
    description: str | None = None
    status: str = "active"  # active, completed, paused
    conversation_ids: Annotated[list[str], Field(default_factory=list)]
    related_topics: Annotated[list[str], Field(default_factory=list)]
    created_at: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    last_updated: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    metadata: Annotated[dict[str, Any], Field(default_factory=dict)]

    @classmethod
    def create(
        cls,
        name: str,
        description: str | None = None,
    ) -> "Thread":
        """Create a new Thread."""
        return cls(
            id=KnowledgeNodeId.generate(),
            name=name,
            description=description,
        )

    def add_conversation(self, conversation_id: str) -> "Thread":
        """Add a conversation to this thread."""
        if conversation_id not in self.conversation_ids:
            return self.model_copy(
                update={
                    "conversation_ids": [*self.conversation_ids, conversation_id],
                    "last_updated": datetime.utcnow(),
                }
            )
        return self


class Expertise(BaseModel):
    """Represents a user's expertise level in a topic."""

    id: KnowledgeNodeId
    topic: str
    level: ExpertiseLevel = ExpertiseLevel.NOVICE
    evidence_count: int = 0
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5
    last_assessed: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    evidence_snippets: Annotated[list[str], Field(default_factory=list)]
    metadata: Annotated[dict[str, Any], Field(default_factory=dict)]

    @classmethod
    def create(
        cls,
        topic: str,
        level: ExpertiseLevel = ExpertiseLevel.NOVICE,
    ) -> "Expertise":
        """Create a new Expertise."""
        return cls(
            id=KnowledgeNodeId.generate(),
            topic=topic,
            level=level,
        )

    def add_evidence(self, snippet: str) -> "Expertise":
        """Add evidence of expertise."""
        return self.model_copy(
            update={
                "evidence_count": self.evidence_count + 1,
                "evidence_snippets": [*self.evidence_snippets[-9:], snippet],  # Keep last 10
                "last_assessed": datetime.utcnow(),
            }
        )


class Preference(BaseModel):
    """Represents an aggregated user preference."""

    id: KnowledgeNodeId
    category: str  # food, activities, schedule, communication, etc.
    subcategory: str | None = None
    value: str
    sentiment: Annotated[float, Field(ge=-1.0, le=1.0)] = 0.5  # -1 = dislike, 1 = like
    mention_count: int = 1
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5
    first_mentioned: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    last_mentioned: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    source_conversations: Annotated[list[str], Field(default_factory=list)]
    metadata: Annotated[dict[str, Any], Field(default_factory=dict)]

    @classmethod
    def create(
        cls,
        category: str,
        value: str,
        sentiment: float = 0.5,
        subcategory: str | None = None,
    ) -> "Preference":
        """Create a new Preference."""
        return cls(
            id=KnowledgeNodeId.generate(),
            category=category,
            value=value,
            sentiment=sentiment,
            subcategory=subcategory,
        )

    def update_mention(self, conversation_id: str | None = None) -> "Preference":
        """Update mention info and optionally add source conversation."""
        updates: dict[str, Any] = {
            "mention_count": self.mention_count + 1,
            "last_mentioned": datetime.utcnow(),
        }
        if conversation_id and conversation_id not in self.source_conversations:
            updates["source_conversations"] = [*self.source_conversations, conversation_id]
        return self.model_copy(update=updates)


class Contradiction(BaseModel):
    """Represents a detected contradiction between facts."""

    id: KnowledgeNodeId
    entity_type: str  # person, pet, location, etc.
    entity_name: str
    attribute: str  # what attribute is contradicted (age, location, etc.)
    old_value: str
    new_value: str
    old_source: str | None = None  # conversation/message ID
    new_source: str | None = None
    severity: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5  # How severe the contradiction
    resolved: bool = False
    resolution: str | None = None  # Which value was chosen or explanation
    detected_at: Annotated[datetime, Field(default_factory=datetime.utcnow)]
    resolved_at: datetime | None = None
    metadata: Annotated[dict[str, Any], Field(default_factory=dict)]

    @classmethod
    def create(
        cls,
        entity_type: str,
        entity_name: str,
        attribute: str,
        old_value: str,
        new_value: str,
        severity: float = 0.5,
    ) -> "Contradiction":
        """Create a new Contradiction."""
        return cls(
            id=KnowledgeNodeId.generate(),
            entity_type=entity_type,
            entity_name=entity_name,
            attribute=attribute,
            old_value=old_value,
            new_value=new_value,
            severity=severity,
        )

    def resolve(self, resolution: str) -> "Contradiction":
        """Mark the contradiction as resolved."""
        return self.model_copy(
            update={
                "resolved": True,
                "resolution": resolution,
                "resolved_at": datetime.utcnow(),
            }
        )
