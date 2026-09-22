"""LLM agent for extracting events from group conversations."""

import os
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIResponsesModel
from agent_system.adapters.outbound.llm.provider import openai_provider


class ExtractedEventSchema(BaseModel):
    """Schema for a single extracted event."""

    title: Annotated[str, Field(description="Brief title for the event (e.g., 'Team lunch', 'Project deadline')")]
    description: Annotated[str | None, Field(default=None, description="More detailed description if available")]
    event_type: Annotated[
        Literal["meeting", "deadline", "activity", "obligation"],
        Field(description="Type of event: meeting (gathering of people), deadline (due date), activity (social/fun event), obligation (commitment/task)")
    ]
    datetime_str: Annotated[
        str | None,
        Field(default=None, description="Date/time mentioned - ALWAYS capture vague references like 'tonight', 'tomorrow', 'this weekend', 'next week', or specific times like 'Tuesday at 3pm'. Even 'tonight' is a valid datetime_str.")
    ]
    location: Annotated[
        str | None,
        Field(default=None, description="Location if mentioned (e.g., 'the park', 'conference room B', 'online')")
    ]
    mentioned_users: Annotated[
        list[str],
        Field(default_factory=list, description="Names or references to people involved (e.g., 'John', 'the whole team', 'everyone')")
    ]
    confidence: Annotated[
        float,
        Field(ge=0.0, le=1.0, description="Confidence score (0.0-1.0) that this is a real planned event, not hypothetical")
    ]


class EventExtractionResult(BaseModel):
    """Result of event extraction from conversation."""

    events: Annotated[
        list[ExtractedEventSchema],
        Field(default_factory=list, description="List of extracted events. Empty if no events found.")
    ]
    reasoning: Annotated[
        str,
        Field(description="Brief explanation of what was found or why no events were extracted")
    ]


EVENT_EXTRACTION_PROMPT = """You are an expert at identifying events, plans, and activities from GROUP CHAT conversations.

IMPORTANT CONTEXT: This is a GROUP CHAT where members coordinate activities together. 
When someone expresses intent or desire to do something with a specific time, treat it as an invitation/suggestion to the group.

EXTRACT when you find:
- ANY mention of doing something at a specific time ("I'd like to play pickleball at 8 PM" = event!)
- Meetings or gatherings being suggested ("Let's meet Tuesday")
- Deadlines being mentioned ("This is due by Friday")
- Activities being proposed ("We should go hiking this weekend")
- Obligations or commitments made ("I'll send you the report tomorrow")
- Expressions of intent with timing ("I want to go to the gym tomorrow at 6am")
- CONFIRMATIONS or DECISIONS about events mentioned earlier ("We're going to X", "Let's do Y", "I'm in for Z")

DO NOT EXTRACT:
- Purely hypothetical without any time reference ("We could maybe go sometime")
- Past events that already happened
- Questions about availability without a proposed time ("Are you free this week?")

CRITICAL: In a group chat, phrases like "I'd like to...", "I want to...", "Anyone up for..." with a TIME are considered event suggestions, NOT hypotheticals. The speaker is implicitly inviting others.

CRITICAL - USING CONVERSATION CONTEXT:
The context is provided ONLY to help fill in details for events mentioned in the CURRENT MESSAGE.
- ONLY extract events that are ANNOUNCED or CONFIRMED in the CURRENT MESSAGE being analyzed
- DO NOT extract events that were mentioned in old context messages - those have already been processed!
- If someone says "We're going to the Queen Legacy show" in the CURRENT MESSAGE and context has full details, use those details
- The user may use shorthand names - match them to events in context for DETAILS only
- NEVER re-extract events from the conversation history - only from the current message!

For each event, identify:
1. WHAT: A brief title and description (use details from context if available)
2. WHEN: ALWAYS capture the datetime_str!
   - If the exact date/time is in the recent context, USE IT (e.g., "Sunday, February 01, 2026 at 03:00 AM")
   - Otherwise use vague references: "tonight", "tomorrow", "this weekend", etc.
   - DO NOT leave datetime_str empty if ANY time reference is available in context!
3. WHERE: Location if mentioned (check context for venue details!)
4. WHO: Which people are involved (by name or reference, can be empty if open invitation)
5. CONFIDENCE: Score 0.9+ if referencing an event with full details in context, 0.8+ for specific times, 0.7+ for vague time

If the conversation is just casual chat with NO mention of activities or times, return an empty events list.
"""


def _get_model_for_extraction(model_string: str, api_key: str | None = None) -> OpenAIResponsesModel | str:
    """Get a model instance for event extraction.
    
    Args:
        model_string: Model string like "openai:gpt-5.2" or "gpt-5.2"
        api_key: Optional API key to use
        
    Returns:
        OpenAIResponsesModel instance if api_key available, otherwise model string
    """
    if ":" in model_string:
        _, model_name = model_string.split(":", 1)
    else:
        model_name = model_string
    
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if key:
        return OpenAIResponsesModel(model_name, provider=openai_provider(key))
    
    return model_string


def create_event_extractor_agent(
    model: str = "openai:gpt-5.2",
    api_key: str | None = None,
) -> Agent[None, EventExtractionResult]:
    """Create an agent for extracting events from conversation text.
    
    Args:
        model: The LLM model to use
        api_key: Optional API key to use
        
    Returns:
        PydanticAI Agent configured for event extraction
    """
    return Agent(
        _get_model_for_extraction(model, api_key),
        output_type=EventExtractionResult,
        system_prompt=EVENT_EXTRACTION_PROMPT,
    )


async def extract_events_from_text(
    text: str,
    model: str = "openai:gpt-5.2",
    api_key: str | None = None,
    context: list[dict[str, str]] | None = None,
    message_timestamp: datetime | None = None,
) -> EventExtractionResult:
    """Extract events from a text snippet with optional conversation context.
    
    Args:
        text: The conversation text to analyze (the current message)
        model: The LLM model to use
        api_key: Optional API key to use
        context: Optional list of recent messages for context, each with 'role' and 'content' keys
                 This helps extract full event details when user references something from recent conversation
        message_timestamp: The timestamp when the message was originally sent.
                          CRITICAL for resolving relative dates like "today", "tomorrow", "tonight".
                          If not provided, current time is used (which can cause date errors for old messages).
        
    Returns:
        EventExtractionResult with found events
    """
    agent = create_event_extractor_agent(model, api_key)
    
    # Build date context - CRITICAL for resolving "today", "tomorrow", etc.
    if message_timestamp:
        date_context = f"""IMPORTANT - MESSAGE DATE CONTEXT:
This message was sent on: {message_timestamp.strftime('%A, %B %d, %Y at %I:%M %p')}
When the message says "today", it means {message_timestamp.strftime('%A, %B %d, %Y')}.
When the message says "tomorrow", it means {(message_timestamp + __import__('datetime').timedelta(days=1)).strftime('%A, %B %d, %Y')}.
When the message says "tonight", it means the evening of {message_timestamp.strftime('%A, %B %d, %Y')}.
ALWAYS resolve relative dates based on when the message was SENT, not the current date.

"""
    else:
        date_context = ""
    
    # Build the prompt with context if available
    if context:
        context_str = "\n".join(
            f"[{msg.get('role', 'user')}]: {msg.get('content', '')}" 
            for msg in context[-10:]  # Last 10 messages max
        )
        full_prompt = f"""{date_context}RECENT CONVERSATION CONTEXT:
{context_str}

---

CURRENT MESSAGE TO ANALYZE (extract events from this, using context above for details):
{text}"""
    else:
        full_prompt = f"{date_context}{text}"
    
    result = await agent.run(full_prompt)
    return result.output
