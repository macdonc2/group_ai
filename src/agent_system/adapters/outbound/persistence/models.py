"""SQLAlchemy ORM models for persistence."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agent_system.adapters.outbound.persistence.database import Base


class UserModel(Base):
    """SQLAlchemy model for User entity."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(1024))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    encrypted_openai_api_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    encrypted_google_refresh_token: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    google_calendar_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    preferences: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    learned_patterns: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    conversations: Mapped[list["ConversationModel"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    plans: Mapped[list["PlanModel"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    group_memberships: Mapped[list["GroupMembershipModel"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ConversationModel(Base):
    """SQLAlchemy model for Conversation entity."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    active_plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    topic_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    total_tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    context_window_size: Mapped[int] = mapped_column(Integer, default=20)
    custom_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    user: Mapped["UserModel"] = relationship(back_populates="conversations")
    messages: Mapped[list["MessageModel"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="MessageModel.created_at",
    )


class MessageModel(Base):
    """SQLAlchemy model for stored messages."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    content_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    conversation: Mapped["ConversationModel"] = relationship(back_populates="messages")


class PlanModel(Base):
    """SQLAlchemy model for Plan entity."""

    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)
    goal_description: Mapped[str] = mapped_column(Text)
    goal_success_criteria: Mapped[list[str]] = mapped_column(JSON, default=list)
    goal_context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    current_step_index: Mapped[int] = mapped_column(Integer, default=0)
    plan_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    user: Mapped["UserModel"] = relationship(back_populates="plans")
    steps: Mapped[list["PlanStepModel"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="PlanStepModel.order",
    )


class PlanStepModel(Base):
    """SQLAlchemy model for plan steps."""

    __tablename__ = "plan_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("plans.id", ondelete="CASCADE"), index=True
    )
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    order: Mapped[int] = mapped_column(Integer)
    dependencies: Mapped[list[int]] = mapped_column(JSON, default=list)
    tool_required: Mapped[str | None] = mapped_column(String(100), nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    step_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    plan: Mapped["PlanModel"] = relationship(back_populates="steps")


# ==================== Group Models ====================


class GroupModel(Base):
    """SQLAlchemy model for Group entity."""

    __tablename__ = "groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    memberships: Mapped[list["GroupMembershipModel"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["GroupConversationModel"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    extracted_events: Mapped[list["ExtractedEventModel"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class GroupMembershipModel(Base):
    """SQLAlchemy model for group membership."""

    __tablename__ = "group_memberships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20), default="member")
    sharing_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    group: Mapped["GroupModel"] = relationship(back_populates="memberships")
    user: Mapped["UserModel"] = relationship(back_populates="group_memberships")


class GroupConversationModel(Base):
    """SQLAlchemy model for group conversations."""

    __tablename__ = "group_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    topic_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    total_tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    context_window_size: Mapped[int] = mapped_column(Integer, default=20)
    participant_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    group: Mapped["GroupModel"] = relationship(back_populates="conversations")
    messages: Mapped[list["GroupMessageModel"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="GroupMessageModel.created_at",
    )


class GroupMessageModel(Base):
    """SQLAlchemy model for group messages."""

    __tablename__ = "group_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    group_conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("group_conversations.id", ondelete="CASCADE"), index=True
    )
    sender_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    content_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    conversation: Mapped["GroupConversationModel"] = relationship(back_populates="messages")


class ExtractedEventModel(Base):
    """SQLAlchemy model for AI-extracted events from conversations."""

    __tablename__ = "extracted_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_type: Mapped[str] = mapped_column(String(50))  # meeting, deadline, activity, obligation
    event_datetime: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    participant_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Google Calendar sync fields
    google_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    google_calendar_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    google_sync_status: Mapped[str] = mapped_column(String(20), default="pending")
    google_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    group: Mapped["GroupModel"] = relationship(back_populates="extracted_events")
