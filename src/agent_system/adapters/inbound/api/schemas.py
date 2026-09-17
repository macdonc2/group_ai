"""API request and response schemas."""

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ============ Auth Schemas ============

class LoginRequest(BaseModel):
    """Schema for login request."""

    email: EmailStr
    password: Annotated[str, Field(min_length=1, description="User password")]


class LoginResponse(BaseModel):
    """Schema for login response."""

    access_token: str
    token_type: str = "bearer"
    user: "UserRead"


class RegisterRequest(BaseModel):
    """Schema for registering a new user (admin only)."""

    email: EmailStr
    password: Annotated[str, Field(min_length=8, description="User password")]
    is_superuser: bool = False


class ChangePasswordRequest(BaseModel):
    """Schema for changing password."""

    current_password: Annotated[str, Field(min_length=1, description="Current password")]
    new_password: Annotated[str, Field(min_length=8, description="New password")]


# ============ User Schemas ============

class UserCreate(BaseModel):
    """Schema for creating a new user."""

    email: EmailStr
    password: Annotated[str, Field(min_length=8, description="User password")]


class UserRead(BaseModel):
    """Schema for reading user data."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str  # Allow .local domains for system users
    is_active: bool
    is_verified: bool
    is_superuser: bool
    timezone: str = "UTC"
    created_at: datetime


class UserUpdate(BaseModel):
    """Schema for updating user data."""

    email: EmailStr | None = None
    password: str | None = None


class UserPreferencesUpdate(BaseModel):
    """Schema for updating user preferences."""

    default_model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    auto_plan: bool | None = None
    verbose_responses: bool | None = None
    preferred_tools: list[str] | None = None


# ============ Conversation Schemas ============

class ConversationCreate(BaseModel):
    """Schema for creating a new conversation."""

    title: str | None = None


class ConversationRead(BaseModel):
    """Schema for reading conversation data."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    title: str | None
    summary: str | None
    message_count: int
    is_archived: bool
    active_plan_id: str | None
    created_at: datetime
    updated_at: datetime


class ConversationUpdate(BaseModel):
    """Schema for updating conversation data."""

    title: str | None = None
    summary: str | None = None
    tags: list[str] | None = None


class MessageCreate(BaseModel):
    """Schema for creating a new message."""

    content: Annotated[str, Field(min_length=1, description="Message content")]


class MessageRead(BaseModel):
    """Schema for reading message data."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    timestamp: datetime
    tool_calls: list[dict[str, Any]]


class ConversationDetail(ConversationRead):
    """Detailed conversation with messages."""

    messages: list[MessageRead]


# ============ Plan Schemas ============

class PlanStepCreate(BaseModel):
    """Schema for creating a plan step."""

    description: str
    tool_required: str | None = None
    dependencies: Annotated[list[int], Field(default_factory=list)]


class PlanCreate(BaseModel):
    """Schema for creating a new plan."""

    goal_description: str
    success_criteria: list[str]
    steps: list[PlanStepCreate]


class PlanStepRead(BaseModel):
    """Schema for reading plan step data."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    description: str
    status: str
    order: int
    tool_required: str | None
    result: str | None
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None


class PlanRead(BaseModel):
    """Schema for reading plan data."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    conversation_id: str
    goal_description: str
    status: str
    progress: float
    current_step_index: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class PlanDetail(PlanRead):
    """Detailed plan with steps."""

    success_criteria: list[str]
    steps: list[PlanStepRead]


class PlanUpdate(BaseModel):
    """Schema for updating plan data."""

    status: str | None = None


# ============ Agent Interaction Schemas ============

class AgentRequest(BaseModel):
    """Schema for sending a message to the agent."""

    message: Annotated[str, Field(min_length=1, description="User message")]
    conversation_id: str | None = None
    persona: str | None = Field(default=None, description="Optional wrestler persona key (macho_man, hulk_hogan, bret_hart, mean_gene, ultimate_warrior)")


class StreamEvent(BaseModel):
    """Schema for SSE stream events during agent workflow execution."""

    event_type: Annotated[
        str,
        Field(description="Event type: node_start, node_complete, tool_result, response, error"),
    ]
    node_name: str | None = None
    message: str
    data: dict[str, Any] | None = None
    timestamp: float
    
    def to_sse(self) -> str:
        """Format as Server-Sent Event."""
        import json
        return f"data: {json.dumps(self.model_dump())}\n\n"


class SuggestionRead(BaseModel):
    """Schema for reading suggestion data."""

    title: str
    description: str
    relevance_score: float
    action_type: str | None


class AgentResponse(BaseModel):
    """Schema for agent response."""

    response: str
    conversation_id: str
    suggestions: list[SuggestionRead]
    plan_created: bool
    plan_updated: bool
    tools_used: list[str]


# ============ Knowledge Graph Schemas ============

class KnowledgeNodeRead(BaseModel):
    """Schema for reading knowledge node data."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    node_type: str
    label: str
    properties: dict[str, Any]
    created_at: datetime


class RelationshipRead(BaseModel):
    """Schema for reading relationship data."""

    source_id: str
    target_id: str
    relation_type: str
    weight: float


class KnowledgeGraphSummary(BaseModel):
    """Summary of user's knowledge graph."""

    node_count: int
    relationship_count: int
    top_topics: list[str]
    recent_intents: list[str]


# ============ Group Schemas ============

class GroupCreate(BaseModel):
    """Schema for creating a new group."""

    name: Annotated[str, Field(min_length=1, max_length=255, description="Group name")]
    description: str | None = None


class GroupRead(BaseModel):
    """Schema for reading group data."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    member_count: int
    created_by: str
    created_at: datetime
    updated_at: datetime


class GroupUpdate(BaseModel):
    """Schema for updating group data."""

    name: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    description: str | None = None


class GroupMemberRead(BaseModel):
    """Schema for reading group member data."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    user_email: str | None = None
    role: str = "member"  # "owner" or "member"
    sharing_enabled: bool
    joined_at: datetime
    last_seen_at: datetime | None


class GroupMemberUpdate(BaseModel):
    """Schema for updating group member settings."""

    sharing_enabled: bool | None = None


class GroupMemberAdd(BaseModel):
    """Schema for adding a member to a group."""

    user_id: str


class GroupDetail(GroupRead):
    """Detailed group with members."""

    members: list[GroupMemberRead]


class GroupConversationCreate(BaseModel):
    """Schema for creating a group conversation."""

    title: str | None = None


class GroupConversationRead(BaseModel):
    """Schema for reading group conversation data."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    group_id: str
    title: str | None
    message_count: int
    participant_count: int
    created_at: datetime
    updated_at: datetime


class GroupMessageRead(BaseModel):
    """Schema for reading group message data."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    sender_id: str
    role: str
    content: str
    timestamp: datetime
    tool_calls: list[dict[str, Any]]


class GroupConversationDetail(GroupConversationRead):
    """Detailed group conversation with messages."""

    messages: list[GroupMessageRead]


class ExtractedEventRead(BaseModel):
    """Schema for reading extracted event data."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    group_id: str
    title: str
    description: str | None
    event_type: str
    event_datetime: datetime | None  # UTC time
    event_datetime_local: str | None = None  # Formatted in user's timezone
    timezone: str = "UTC"  # User's timezone for display
    location: str | None
    participant_ids: list[str]
    confidence: float
    is_confirmed: bool
    created_at: datetime
    # Google Calendar sync fields
    google_event_id: str | None = None
    google_sync_status: str = "pending"


class ExtractedEventUpdate(BaseModel):
    """Schema for updating an extracted event."""

    title: str | None = None
    description: str | None = None
    event_datetime: datetime | None = None
    location: str | None = None
    is_confirmed: bool | None = None


class SocialSuggestionRead(BaseModel):
    """Schema for reading social suggestions."""

    title: str
    description: str
    suggested_participants: list[str]
    reason: str
    event_type: str | None = None


class GroupSummaryRead(BaseModel):
    """Schema for reading group summary."""

    themes: list[str]
    upcoming_events: list[ExtractedEventRead]
    social_suggestions: list[SocialSuggestionRead]
    active_member_ids: list[str]
    message_count_week: int


# ============ Deep Research Schemas ============

class ResearchCreate(BaseModel):
    """Start a research run from a question or topic."""

    question: Annotated[str, Field(min_length=8, max_length=2000)]
    depth: Annotated[int, Field(ge=1, le=3, description="Research rounds per lane: 1 quick, 2 standard, 3 deep")] = 1
    persona: str | None = Field(default=None, description="Optional wrestler persona key voicing the overview and narration")


class SourceRead(BaseModel):
    id: str
    lane: str
    title: str
    url: str | None = None
    authors: list[str] = []
    year: int | None = None
    venue: str | None = None
    ref: int | None = None


class FigureRead(BaseModel):
    ordinal: int
    caption: str
    source_ids: list[str] = []
    origin: str = "generated"
    source_url: str | None = None
    source_title: str | None = None


class ResearchListItem(BaseModel):
    id: str
    question: str
    title: str | None = None
    status: str
    phase: str
    created_at: datetime
    completed_at: datetime | None = None
    has_audio: bool = False
    figures: int = 0
    depth: int = 1
    persona: str | None = None
    error: str | None = None


class ResearchDetail(ResearchListItem):
    tldr: str | None = None
    report_markdown: str | None = None
    progress: dict[str, Any] = {}
    model: str = ""
    sources: list[SourceRead] = []
    figure_list: list[FigureRead] = []
