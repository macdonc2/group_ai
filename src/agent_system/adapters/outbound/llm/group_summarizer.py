"""LLM agent for generating group summaries and extracting themes."""

from typing import Annotated

from pydantic import BaseModel, Field
from pydantic_ai import Agent


class ThemeSummary(BaseModel):
    """A theme or topic from group conversations."""

    theme: Annotated[str, Field(description="Brief name of the theme (e.g., 'Project planning', 'Weekend activities')")]
    description: Annotated[str, Field(description="Short description of what was discussed about this theme")]
    relevance: Annotated[float, Field(ge=0.0, le=1.0, description="How prominent this theme is (0.0-1.0)")]
    active_participants: Annotated[list[str], Field(default_factory=list, description="Names/IDs of users who discussed this theme")]


class GroupSummaryResult(BaseModel):
    """Result of group summary generation."""

    overall_summary: Annotated[str, Field(description="2-3 sentence summary of the group's recent activity")]
    themes: Annotated[list[ThemeSummary], Field(default_factory=list, description="Main themes discussed (max 5)")]
    active_topics: Annotated[list[str], Field(default_factory=list, description="Currently active topics that might benefit from follow-up")]
    mood: Annotated[str, Field(description="Overall mood/tone of conversations (e.g., 'productive', 'casual', 'planning-focused')")]
    notable_moments: Annotated[list[str], Field(default_factory=list, description="Any notable decisions, agreements, or highlights")]


GROUP_SUMMARY_PROMPT = """You are an expert at summarizing group conversations and extracting meaningful insights.

Given a collection of recent group conversation messages, provide:

1. OVERALL SUMMARY: A brief 2-3 sentence overview of what the group has been discussing
2. THEMES: The main topics/themes (max 5), with who's been involved in each
3. ACTIVE TOPICS: Topics that seem ongoing and might need follow-up
4. MOOD: The general tone of the conversations
5. NOTABLE MOMENTS: Any decisions made, agreements reached, or highlights

Focus on substance over small talk. Identify patterns and connections between discussions.

Be concise but insightful - help members quickly understand what's been happening.
"""


def create_group_summarizer_agent(model: str = "openai:gpt-5.2") -> Agent[None, GroupSummaryResult]:
    """Create an agent for generating group summaries.
    
    Args:
        model: The LLM model to use
        
    Returns:
        PydanticAI Agent configured for group summarization
    """
    return Agent(
        model,
        output_type=GroupSummaryResult,
        system_prompt=GROUP_SUMMARY_PROMPT,
    )


async def generate_group_summary(
    messages_text: str,
    model: str = "openai:gpt-5.2",
) -> GroupSummaryResult:
    """Generate a summary of group conversations.
    
    Args:
        messages_text: Formatted text of recent messages
        model: The LLM model to use
        
    Returns:
        GroupSummaryResult with themes and insights
    """
    agent = create_group_summarizer_agent(model)
    result = await agent.run(messages_text)
    return result.output


class SocialMatchResult(BaseModel):
    """Result of social matching analysis."""

    suggestions: Annotated[
        list["SocialSuggestion"],
        Field(default_factory=list, description="Social activity suggestions")
    ]
    common_interests: Annotated[
        list[str],
        Field(default_factory=list, description="Interests shared by multiple members")
    ]
    potential_collaborations: Annotated[
        list[str],
        Field(default_factory=list, description="Areas where members could collaborate")
    ]


class SocialSuggestion(BaseModel):
    """A suggestion for social activity or connection."""

    title: Annotated[str, Field(description="Brief title for the suggestion")]
    description: Annotated[str, Field(description="What the suggestion is about")]
    suggested_participants: Annotated[list[str], Field(default_factory=list, description="Who might be interested")]
    reason: Annotated[str, Field(description="Why this is suggested based on conversations")]
    activity_type: Annotated[str, Field(description="Type: social, collaborative, learning, fun")]


SOCIAL_MATCHING_PROMPT = """You are an expert at identifying social connections and activity opportunities within groups.

Analyze the group's conversations, events, and member interests to suggest:

1. SOCIAL ACTIVITIES: Things the group or subgroups might enjoy doing together
2. CONNECTIONS: Members with shared interests who might not know it
3. COLLABORATIONS: Opportunities for members to work together on shared goals

Consider:
- Mentioned hobbies, interests, and preferences
- Events being planned and who might also enjoy them
- Common topics that excite multiple people
- Gaps where someone's expertise could help another

Be creative but grounded in what's actually been discussed.
Suggest concrete, actionable ideas rather than vague possibilities.
"""


def create_social_matcher_agent(model: str = "openai:gpt-5.2") -> Agent[None, SocialMatchResult]:
    """Create an agent for social matching and suggestions.
    
    Args:
        model: The LLM model to use
        
    Returns:
        PydanticAI Agent configured for social matching
    """
    return Agent(
        model,
        output_type=SocialMatchResult,
        system_prompt=SOCIAL_MATCHING_PROMPT,
    )


async def generate_social_suggestions(
    context_text: str,
    model: str = "openai:gpt-5.2",
) -> SocialMatchResult:
    """Generate social suggestions for a group.
    
    Args:
        context_text: Formatted text of conversations, events, and member info
        model: The LLM model to use
        
    Returns:
        SocialMatchResult with suggestions
    """
    agent = create_social_matcher_agent(model)
    result = await agent.run(context_text)
    return result.output
