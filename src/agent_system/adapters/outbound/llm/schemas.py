"""Pydantic schemas for LLM agent outputs."""

from typing import Annotated

from pydantic import BaseModel, Field


class IntentAnalysis(BaseModel):
    """Structured output for intent analysis."""

    intent_type: Annotated[
        str,
        Field(description="Type of intent: question, task, exploration, clarification, feedback, command, or meta (asking about the assistant's capabilities/tools)"),
    ]
    description: Annotated[str, Field(description="Brief description of the user's intent")]
    confidence: Annotated[
        float, Field(ge=0.0, le=1.0, description="Confidence score for this analysis")
    ]
    entities: Annotated[
        list[str], Field(default_factory=list, description="Extracted NAMED entities (people, pets, places, specific things) from the input. Extract individual names, not phrases. Example: 'What should I do for Zane's birthday?' -> entities: ['Zane'], not ['Zane's birthday']")
    ]
    requires_planning: Annotated[
        bool, Field(description="Whether this intent requires creating a plan")
    ]
    is_about_assistant: Annotated[
        bool, Field(description="True if user is asking about the assistant itself - its capabilities, tools, features, or what it can do")
    ]
    suggested_tool: Annotated[
        str | None,
        Field(
            default=None,
            description="Tool to use if one is needed. Options: 'web_search' (for real-time info NOT related to events/schedule/app features), 'calculate' (for math), 'define_word' (for definitions), 'random_fact' (for trivia), 'get_current_datetime' (for time), 'summarize_user_knowledge' (when user asks 'what do you know about me'), 'recall_about_topic' (CRITICAL: when user asks about a SPECIFIC person, pet, or topic like 'Tell me about Bo' or 'What do you know about Zane'), 'get_upcoming_events' (for PERSONAL schedule/plans - 'What do I have planned?', 'Any meetings this week?', 'When is my haircut?'), 'get_houston_events' (CRITICAL: for Houston area events, concerts, activities, things to do - 'Houston events', 'What's happening this weekend?', 'Any concerts tonight?', 'Events in Montrose'. This searches the curated Houston events database.), 'add_to_calendar' (CRITICAL: when the user wants an event PUT ON their calendar - 'put X on my calendar', 'add X to my calendar', 'schedule X', 'remind me about X'. Command, not a question.), 'search_internal_docs' (CRITICAL: when user asks about the APP ITSELF or how features work - 'How do groups work?', 'How do I connect my calendar?', 'What tools do you have?', 'How does memory work?', 'How do I set my timezone?', 'How does the knowledge graph work?', 'How do I get started?'. Searches built-in documentation.), or null if no tool needed"
        )
    ]
    tool_input: Annotated[
        str | None,
        Field(
            default=None,
            description="The extracted input for the tool. For calculate: the mathematical expression (e.g., '1+3-4'). For web_search: a specific search query WITH date/location context (e.g., 'Houston events January 2026' not just 'events'). For define_word: the word to define. For get_upcoming_events: combine timeframe ('today', 'tomorrow', 'week', 'month'), keywords ('haircut', 'meeting'), temporal ('past', 'future'), or specific dates ('January 30') - e.g., 'haircut' to find a haircut appointment, 'past meeting' for past meetings. For add_to_calendar: the event name plus any date/time words, with pronouns resolved to the real event name (e.g. 'Punk Rock Garage Sale', 'dentist Tuesday 3pm'). For search_internal_docs: key terms about the feature (e.g., 'groups', 'calendar sync', 'events', 'knowledge graph', 'settings', 'getting started', 'tools capabilities')."
        )
    ]


class PlanStepSchema(BaseModel):
    """Schema for a single plan step."""

    description: Annotated[str, Field(description="Description of what this step accomplishes")]
    tool_required: Annotated[
        str | None, Field(default=None, description="Tool needed for this step, if any")
    ]
    dependencies: Annotated[
        list[int],
        Field(default_factory=list, description="Indices of steps this depends on"),
    ]


class PlanSchema(BaseModel):
    """Structured output for plan creation."""

    goal_description: Annotated[str, Field(description="Clear description of the goal")]
    success_criteria: Annotated[
        list[str], Field(description="List of criteria that indicate success")
    ]
    steps: Annotated[list[PlanStepSchema], Field(description="Ordered list of steps to achieve the goal")]
    estimated_complexity: Annotated[
        str, Field(description="Complexity level: simple, moderate, complex")
    ]


class ToolSelection(BaseModel):
    """Structured output for tool selection."""

    tool_name: Annotated[str, Field(description="Name of the tool to use")]
    arguments: Annotated[
        dict[str, str], Field(description="Arguments to pass to the tool")
    ]
    reasoning: Annotated[str, Field(description="Brief explanation of why this tool was selected")]


class ResponseGeneration(BaseModel):
    """Structured output for response generation."""

    response: Annotated[
        str, 
        Field(
            min_length=300,
            description="""A THOROUGH, COMPREHENSIVE response. MINIMUM 4-6 paragraphs or 300+ words.

Structure your response to include:
1. ACKNOWLEDGMENT: React to what they shared with genuine engagement
2. DEPTH: Share relevant knowledge, context, insights, or perspectives  
3. EXPLORATION: Discuss related angles, considerations, or interesting tangents
4. CONNECTION: Relate to broader themes or your own observations
5. ENGAGEMENT: End with thoughtful questions or prompts for continued discussion

Think of yourself as an articulate friend who loves diving deep into topics. Never give brief, surface-level answers. If discussing a pet, talk about breed characteristics, care considerations, personality quirks. If discussing a topic, explore multiple facets and share interesting related information."""
        )
    ]
    suggestions: Annotated[
        list[str],
        Field(default_factory=list, description="2-3 SHORT, SPECIFIC follow-up suggestions as action chips. Make them contextual to the conversation - reference entities, topics, or tools used. Examples: 'Events near Montrose', 'Tell me about Zane', 'Cycling this weekend'. NOT generic like 'Learn more' or 'Fun fact'."),
    ]


class KnowledgeExtraction(BaseModel):
    """Structured output for knowledge extraction."""

    topics: Annotated[
        list[str], 
        Field(default_factory=list, description="Topics the user is interested in or discussing")
    ]
    entities: Annotated[
        list[str],
        Field(default_factory=list, description="Important facts to remember, e.g. 'User has a friend named Zane', 'Zane has a bird'"),
    ]
    user_preferences: Annotated[
        list[str],
        Field(default_factory=list, description="User preferences or communication style notes"),
    ]


class StepExecution(BaseModel):
    """ReAct-style structured output for executing a single plan step."""

    thought: Annotated[
        str,
        Field(description="Your reasoning about this step - what you're thinking, what knowledge you're drawing on, what considerations apply")
    ]
    action: Annotated[
        str,
        Field(description="The action you're taking for this step - either 'think' (use knowledge), 'search' (needs tool), or 'recall' (from context)")
    ]
    observation: Annotated[
        str,
        Field(description="The result or insight from executing this step - what you learned, discovered, or concluded")
    ]
    needs_tool: Annotated[
        bool,
        Field(description="True if this step requires an external tool (web search, calculator, etc.) to complete properly")
    ]
    tool_suggestion: Annotated[
        str | None,
        Field(default=None, description="If needs_tool is True, which tool: 'web_search', 'calculate', 'get_upcoming_events', etc.")
    ]


class ReActPlanSchema(BaseModel):
    """Enhanced plan schema for ReAct-style reasoning."""

    goal_description: Annotated[str, Field(description="Clear description of what we're trying to accomplish")]
    reasoning_approach: Annotated[
        str, 
        Field(description="Brief description of how we'll approach this problem - the overall strategy")
    ]
    steps: Annotated[
        list[PlanStepSchema], 
        Field(
            min_length=3,
            max_length=6,
            description="""3-6 reasoning steps to work through the problem. Each step should be a distinct phase of thinking:
            - Step 1: Usually 'Understand the core question/goal' 
            - Middle steps: Break down key aspects, considerations, or sub-problems
            - Final step: Usually 'Synthesize into actionable guidance'
            
            Examples for 'How to make sourdough starter':
            1. Understand the fundamentals of sourdough fermentation
            2. Identify required ingredients and equipment  
            3. Work through the day-by-day process
            4. Address common issues and troubleshooting
            5. Define success indicators"""
        )
    ]
    success_criteria: Annotated[
        list[str], Field(description="How we'll know the response is complete and helpful")
    ]
    estimated_complexity: Annotated[
        str, Field(description="Complexity level: simple, moderate, complex")
    ]


class StepSynthesis(BaseModel):
    """Structured output for synthesizing step results into final response."""

    synthesized_response: Annotated[
        str,
        Field(
            min_length=400,
            description="""A comprehensive response that weaves together all the reasoning steps.
            
            Structure:
            1. Brief intro acknowledging the question
            2. Main content organized logically (can use headings, lists, etc.)
            3. Practical guidance or key takeaways
            4. Closing that invites follow-up
            
            Should feel like a natural, helpful response - not just a list of step outputs."""
        )
    ]
    key_insights: Annotated[
        list[str],
        Field(description="2-4 key insights or takeaways from the reasoning process")
    ]
    follow_up_suggestions: Annotated[
        list[str],
        Field(default_factory=list, description="2-3 natural follow-up topics or questions")
    ]
