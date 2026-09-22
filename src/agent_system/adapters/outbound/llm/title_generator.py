"""Generate meaningful conversation titles using LLM."""

import os
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIResponsesModel
from agent_system.adapters.outbound.llm.provider import openai_provider
from typing import Annotated


class ConversationTitle(BaseModel):
    """Generated conversation title."""
    
    title: Annotated[str, Field(
        description="A short, descriptive title for the conversation (3-6 words)",
        max_length=50
    )]


TITLE_SYSTEM_PROMPT = """You generate short, descriptive titles for conversations.

Rules:
- Keep titles between 3-6 words
- Make them descriptive of the main topic or intent
- Use title case
- Don't use quotes or special characters
- Be specific, not generic

Examples of good titles:
- "Python Web Scraping Help"
- "Morning Coffee Recipe"
- "React Component Debugging"
- "Weekend Trip Planning"
- "Math Homework Questions"
"""


def _get_model_for_title(model_string: str, api_key: str | None = None) -> OpenAIResponsesModel | str:
    """Get a model instance for title generation."""
    if ":" in model_string:
        _, model_name = model_string.split(":", 1)
    else:
        model_name = model_string
    
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if key:
        return OpenAIResponsesModel(model_name, provider=openai_provider(key))
    
    return model_string


async def generate_conversation_title(
    first_message: str,
    model: str = "openai:gpt-5-mini",
    api_key: str | None = None,
) -> str:
    """Generate a meaningful title from the first message of a conversation.
    
    Args:
        first_message: The first user message in the conversation
        model: The LLM model to use (default: gpt-5-mini for speed/cost)
        api_key: Optional API key to use
        
    Returns:
        A short, descriptive title for the conversation
    """
    try:
        agent = Agent(
            _get_model_for_title(model, api_key),
            output_type=ConversationTitle,
            system_prompt=TITLE_SYSTEM_PROMPT,
        )
        
        prompt = f"Generate a short title for a conversation that starts with: {first_message[:200]}"
        result = await agent.run(prompt)
        return result.output.title
        
    except Exception as e:
        # Fallback: extract first few words from message
        words = first_message.split()[:5]
        title = " ".join(words)
        if len(title) > 40:
            title = title[:37] + "..."
        return title or "New Conversation"
