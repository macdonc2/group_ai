"""LLM agent for extracting entities (people, pets, locations) from conversations."""

import logging
import os
from typing import Annotated, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

logger = logging.getLogger(__name__)


# ============ Extracted Entity Schemas ============


class ExtractedPerson(BaseModel):
    """A person mentioned in conversation."""

    name: Annotated[str, Field(description="The person's name as mentioned")]
    aliases: Annotated[
        list[str],
        Field(
            default_factory=list,
            description="Other names/references used for this person (e.g., 'Dom' for 'Dominique', 'my wife', 'the boss')",
        ),
    ]
    relationship_type: Annotated[
        Literal[
            "spouse",
            "partner",
            "family",
            "parent",
            "child",
            "sibling",
            "friend",
            "colleague",
            "acquaintance",
            "mentor",
            "client",
            "neighbor",
            None,
        ],
        Field(default=None, description="Relationship to the user if mentioned or implied"),
    ]
    context_notes: Annotated[
        str | None,
        Field(default=None, description="Any contextual information about this person"),
    ]
    confidence: Annotated[
        float,
        Field(ge=0.0, le=1.0, description="Confidence this is a real person being discussed"),
    ]


class ExtractedPet(BaseModel):
    """A pet mentioned in conversation."""

    name: Annotated[str, Field(description="The pet's name")]
    aliases: Annotated[
        list[str],
        Field(
            default_factory=list,
            description="Other names/references (e.g., 'Bo Boy' for 'Bo', 'the dog')",
        ),
    ]
    species: Annotated[
        str | None,
        Field(default=None, description="Species: dog, cat, bird, fish, rabbit, etc."),
    ]
    breed: Annotated[
        str | None,
        Field(default=None, description="Breed if mentioned"),
    ]
    traits: Annotated[
        list[str],
        Field(
            default_factory=list,
            description="Personality traits mentioned (playful, lazy, food-motivated, etc.)",
        ),
    ]
    food_preferences: Annotated[
        list[str],
        Field(default_factory=list, description="Foods the pet likes or dislikes"),
    ]
    confidence: Annotated[
        float,
        Field(ge=0.0, le=1.0, description="Confidence this is a real pet being discussed"),
    ]


class ExtractedLocation(BaseModel):
    """A location mentioned in conversation."""

    name: Annotated[str, Field(description="The location's name")]
    aliases: Annotated[
        list[str],
        Field(default_factory=list, description="Other names for this location"),
    ]
    location_type: Annotated[
        Literal[
            "restaurant",
            "cafe",
            "bar",
            "gym",
            "office",
            "home",
            "park",
            "store",
            "venue",
            "school",
            "hospital",
            "salon",
            "other",
            None,
        ],
        Field(default=None, description="Type of location"),
    ]
    address: Annotated[
        str | None,
        Field(default=None, description="Street address if mentioned"),
    ]
    city: Annotated[
        str | None,
        Field(default=None, description="City if mentioned"),
    ]
    associated_activity: Annotated[
        str | None,
        Field(default=None, description="What activity is done here (cycling, dining, working, etc.)"),
    ]
    confidence: Annotated[
        float,
        Field(ge=0.0, le=1.0, description="Confidence this is a real location being discussed"),
    ]


class ExtractedRelationship(BaseModel):
    """A relationship between entities."""

    source_name: Annotated[str, Field(description="Name of the first entity")]
    source_type: Annotated[
        Literal["person", "pet", "location", "user"],
        Field(description="Type of the first entity"),
    ]
    relationship: Annotated[
        str,
        Field(description="The relationship type (e.g., 'works_at', 'friend_of', 'lives_in', 'owns')"),
    ]
    target_name: Annotated[str, Field(description="Name of the second entity")]
    target_type: Annotated[
        Literal["person", "pet", "location", "user"],
        Field(description="Type of the second entity"),
    ]
    confidence: Annotated[
        float,
        Field(ge=0.0, le=1.0, description="Confidence in this relationship"),
    ]


class ExtractedPreference(BaseModel):
    """A user preference mentioned in conversation."""

    category: Annotated[
        str,
        Field(description="Category: food, activities, schedule, communication, entertainment, etc."),
    ]
    subcategory: Annotated[
        str | None,
        Field(default=None, description="Subcategory if applicable"),
    ]
    value: Annotated[str, Field(description="The specific preference value")]
    sentiment: Annotated[
        Literal["likes", "dislikes", "prefers", "avoids", "neutral"],
        Field(description="Sentiment toward this preference"),
    ]
    confidence: Annotated[
        float,
        Field(ge=0.0, le=1.0, description="Confidence in this preference"),
    ]


class KnowledgeExtractionResult(BaseModel):
    """Complete result of knowledge extraction from conversation."""

    persons: Annotated[
        list[ExtractedPerson],
        Field(default_factory=list, description="People mentioned in the conversation"),
    ]
    pets: Annotated[
        list[ExtractedPet],
        Field(default_factory=list, description="Pets mentioned in the conversation"),
    ]
    locations: Annotated[
        list[ExtractedLocation],
        Field(default_factory=list, description="Locations mentioned in the conversation"),
    ]
    relationships: Annotated[
        list[ExtractedRelationship],
        Field(default_factory=list, description="Relationships between entities"),
    ]
    preferences: Annotated[
        list[ExtractedPreference],
        Field(default_factory=list, description="User preferences mentioned"),
    ]
    reasoning: Annotated[
        str,
        Field(description="Brief explanation of what was extracted"),
    ]


# ============ Extraction Prompt ============


KNOWLEDGE_EXTRACTION_PROMPT = """You are an expert at extracting structured knowledge from conversations.
Your job is to identify and extract:

1. **PEOPLE** - Anyone mentioned by name or reference
   - Direct names: "John", "Sarah", "Dr. Smith"
   - References: "my wife", "his boss", "the team"
   - Include relationship type if clear (spouse, friend, colleague, etc.)
   - Capture any aliases (nicknames, titles, references)

2. **PETS** - Any pets mentioned
   - Names and nicknames
   - Species (dog, cat, bird, etc.) and breed if mentioned
   - Personality traits and behaviors
   - Food preferences (likes carrots, needs special diet, etc.)

3. **LOCATIONS** - Places mentioned
   - Restaurants, bars, cafes
   - Gyms, parks, venues
   - Offices, homes, schools
   - Include address/city if mentioned
   - Note what activities happen there

4. **RELATIONSHIPS** - Connections between entities
   - Person-Person: "John works with Sarah", "my wife's friend"
   - Person-Location: "Brandon at In The Loop salon"
   - Person-Pet: "Sarah's cat"
   - Use relationship types: works_at, friend_of, lives_in, owns, related_to, etc.

5. **PREFERENCES** - User likes/dislikes
   - Food preferences: "I love sushi", "I don't eat spicy food"
   - Activity preferences: "I prefer morning workouts"
   - Schedule preferences: "I like quiet evenings"

IMPORTANT GUIDELINES:
- Only extract entities with high confidence (≥0.7)
- Resolve coreferences: "his wife" → look for who "his" refers to
- Don't extract generic mentions: "a restaurant" (no name = skip)
- DO extract even partial information - it can be enriched later
- For relationships, always identify both source and target entities
- The "user" is always the person speaking in user messages

If the conversation is casual chat with no extractable entities, return empty lists with appropriate reasoning.
"""


# ============ Model and Agent Setup ============


def _get_model_for_extraction(model_string: str, api_key: str | None = None) -> OpenAIModel | str:
    """Get a model instance for knowledge extraction.

    Args:
        model_string: Model string like "openai:gpt-5.2" or "gpt-5.2"
        api_key: Optional API key to use

    Returns:
        OpenAIModel instance if api_key available, otherwise model string
    """
    if ":" in model_string:
        _, model_name = model_string.split(":", 1)
    else:
        model_name = model_string

    key = api_key or os.environ.get("OPENAI_API_KEY")
    if key:
        return OpenAIModel(model_name, provider=OpenAIProvider(api_key=key))

    return model_string


def create_knowledge_extractor_agent(
    model: str = "openai:gpt-5.2",
    api_key: str | None = None,
) -> Agent[None, KnowledgeExtractionResult]:
    """Create an agent for extracting knowledge from conversation text.

    Args:
        model: The LLM model to use
        api_key: Optional API key to use

    Returns:
        PydanticAI Agent configured for knowledge extraction
    """
    return Agent(
        _get_model_for_extraction(model, api_key),
        output_type=KnowledgeExtractionResult,
        system_prompt=KNOWLEDGE_EXTRACTION_PROMPT,
    )


async def extract_knowledge_from_text(
    text: str,
    model: str = "openai:gpt-5.2",
    api_key: str | None = None,
    context: list[dict[str, str]] | None = None,
    existing_persons: list[str] | None = None,
    existing_pets: list[str] | None = None,
    existing_locations: list[str] | None = None,
) -> KnowledgeExtractionResult:
    """Extract knowledge entities from a text snippet.

    Args:
        text: The conversation text to analyze
        model: The LLM model to use
        api_key: Optional API key to use
        context: Optional list of recent messages for context
        existing_persons: Names of people already known (for reference resolution)
        existing_pets: Names of pets already known
        existing_locations: Names of locations already known

    Returns:
        KnowledgeExtractionResult with extracted entities
    """
    agent = create_knowledge_extractor_agent(model, api_key)

    # Build context-aware prompt
    prompt_parts = []

    # Add existing knowledge context
    if existing_persons or existing_pets or existing_locations:
        prompt_parts.append("KNOWN ENTITIES (use for reference resolution):")
        if existing_persons:
            prompt_parts.append(f"- Known people: {', '.join(existing_persons)}")
        if existing_pets:
            prompt_parts.append(f"- Known pets: {', '.join(existing_pets)}")
        if existing_locations:
            prompt_parts.append(f"- Known locations: {', '.join(existing_locations)}")
        prompt_parts.append("")

    # Add conversation context
    if context:
        context_str = "\n".join(
            f"[{msg.get('role', 'user')}]: {msg.get('content', '')}"
            for msg in context[-10:]
        )
        prompt_parts.append("RECENT CONVERSATION CONTEXT:")
        prompt_parts.append(context_str)
        prompt_parts.append("")

    # Add the current message
    prompt_parts.append("CURRENT MESSAGE TO ANALYZE:")
    prompt_parts.append(text)

    full_prompt = "\n".join(prompt_parts)

    try:
        result = await agent.run(full_prompt)
        return result.output
    except Exception as e:
        logger.error(f"Knowledge extraction failed: {e}")
        return KnowledgeExtractionResult(
            persons=[],
            pets=[],
            locations=[],
            relationships=[],
            preferences=[],
            reasoning=f"Extraction failed (text): {str(e)}",
        )


async def extract_knowledge_from_conversation(
    messages: list[dict[str, str]],
    model: str = "openai:gpt-5.2",
    api_key: str | None = None,
    existing_persons: list[str] | None = None,
    existing_pets: list[str] | None = None,
    existing_locations: list[str] | None = None,
) -> KnowledgeExtractionResult:
    """Extract knowledge from an entire conversation.

    This processes multiple messages together for better context understanding.

    Args:
        messages: List of messages, each with 'role' and 'content'
        model: The LLM model to use
        api_key: Optional API key to use
        existing_persons: Names of people already known
        existing_pets: Names of pets already known
        existing_locations: Names of locations already known

    Returns:
        KnowledgeExtractionResult with extracted entities
    """
    agent = create_knowledge_extractor_agent(model, api_key)

    # Build the full conversation prompt
    prompt_parts = []

    # Add existing knowledge context
    if existing_persons or existing_pets or existing_locations:
        prompt_parts.append("KNOWN ENTITIES (use for reference resolution):")
        if existing_persons:
            prompt_parts.append(f"- Known people: {', '.join(existing_persons)}")
        if existing_pets:
            prompt_parts.append(f"- Known pets: {', '.join(existing_pets)}")
        if existing_locations:
            prompt_parts.append(f"- Known locations: {', '.join(existing_locations)}")
        prompt_parts.append("")

    # Add full conversation
    prompt_parts.append("FULL CONVERSATION TO ANALYZE:")
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        prompt_parts.append(f"[{role}]: {content}")

    full_prompt = "\n".join(prompt_parts)

    try:
        result = await agent.run(full_prompt)
        return result.output
    except Exception as e:
        logger.error(f"Knowledge extraction failed: {e}")
        return KnowledgeExtractionResult(
            persons=[],
            pets=[],
            locations=[],
            relationships=[],
            preferences=[],
            reasoning=f"Extraction failed (conversation): {str(e)}",
        )


# ============ Entity Type Detection ============


class EntityTypeResult(BaseModel):
    """Result of entity type detection."""

    entity_name: Annotated[str, Field(description="The entity name being analyzed")]
    entity_type: Annotated[
        Literal["pet", "person", "location", "unknown"],
        Field(description="The type of entity"),
    ]
    species: Annotated[
        str | None,
        Field(default=None, description="For pets: the species (dog, cat, bird, etc.)"),
    ]
    breed: Annotated[
        str | None,
        Field(default=None, description="For pets: the breed if mentioned"),
    ]
    relationship: Annotated[
        str | None,
        Field(default=None, description="For people: relationship to user (spouse, friend, etc.)"),
    ]
    description: Annotated[
        str | None,
        Field(default=None, description="Brief description of the entity"),
    ]
    confidence: Annotated[
        float,
        Field(ge=0.0, le=1.0, description="Confidence in the entity type determination"),
    ]


ENTITY_TYPE_DETECTION_PROMPT = """You are an entity type classifier. Given text snippets that mention an entity name, determine what type of entity it is.

ENTITY TYPES:
- "pet": An animal owned by the user (dog, cat, bird, fish, etc.)
- "person": A human being (family member, friend, colleague, etc.)
- "location": A place (restaurant, city, office, park, etc.)
- "unknown": Cannot determine from the given text

IMPORTANT:
- Look for keywords that indicate type:
  - Pet indicators: "my dog", "my cat", "pet", animal names, species mentions
  - Person indicators: "my wife", "my friend", family titles, human activities
  - Location indicators: "restaurant", "at the", addresses, city names
- Pay attention to context clues (what activities are described)
- If someone has an unusual name that could be a pet or person, look for context clues

EXAMPLES:
- "Zane is my dog and he's an old man baby" → pet (species: dog)
- "Sarah and I went to dinner" → person (likely spouse/partner/friend)
- "We love going to Uchi for sushi" → location (restaurant)
- "Bo Boy is my older male, black cat" → pet (species: cat)

Analyze the text and return the entity type with confidence."""


def create_entity_type_detector_agent(
    model: str = "openai:gpt-5-mini",
    api_key: str | None = None,
) -> Agent[None, EntityTypeResult]:
    """Create an agent for detecting entity types from text."""
    key = api_key or os.environ.get("OPENAI_API_KEY")

    if key and ":" in model:
        _, model_name = model.split(":", 1)
        model_instance = OpenAIModel(model_name, provider=OpenAIProvider(api_key=key))
    else:
        model_instance = model  # type: ignore

    return Agent(
        model_instance,
        output_type=EntityTypeResult,
        system_prompt=ENTITY_TYPE_DETECTION_PROMPT,
    )


async def detect_entity_type(
    entity_name: str,
    text_snippets: list[str],
    model: str = "openai:gpt-5-mini",
    api_key: str | None = None,
) -> EntityTypeResult:
    """Detect the type of an entity from text snippets mentioning it.

    Args:
        entity_name: The name of the entity to classify
        text_snippets: List of text snippets that mention the entity
        model: The LLM model to use
        api_key: Optional API key

    Returns:
        EntityTypeResult with the detected type and metadata
    """
    agent = create_entity_type_detector_agent(model, api_key)

    # Build the prompt with the entity name and snippets
    prompt_parts = [
        f"Entity name to classify: {entity_name}",
        "",
        "Text snippets mentioning this entity:",
    ]
    for i, snippet in enumerate(text_snippets[:5], 1):  # Limit to 5 snippets
        # Truncate long snippets
        snippet_text = snippet[:300] if len(snippet) > 300 else snippet
        prompt_parts.append(f"{i}. {snippet_text}")

    prompt = "\n".join(prompt_parts)

    try:
        result = await agent.run(prompt)
        return result.output
    except Exception as e:
        logger.error(f"Entity type detection failed for {entity_name}: {e}")
        return EntityTypeResult(
            entity_name=entity_name,
            entity_type="unknown",
            confidence=0.0,
        )
