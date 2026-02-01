"""Ports - Abstract interfaces for external dependencies."""

from agent_system.domain.ports.calendar import (
    GoogleCalendarInfo,
    GoogleCalendarPort,
    GoogleUserInfo,
    OAuthTokens,
)
from agent_system.domain.ports.clock import ClockPort, SystemClock
from agent_system.domain.ports.embedding import EmbeddingPort, EmbeddingResult
from agent_system.domain.ports.id_generator import (
    DeterministicIdGenerator,
    IdGeneratorPort,
    UUIDGenerator,
)
from agent_system.domain.ports.knowledge_graph import KnowledgeGraphPort
from agent_system.domain.ports.llm import LLMConfig, LLMPort, LLMResponse
from agent_system.domain.ports.repositories import (
    ConversationRepository,
    PlanRepository,
    Repository,
    UserRepository,
)

__all__ = [
    # Base
    "Repository",
    # Repositories
    "UserRepository",
    "ConversationRepository",
    "PlanRepository",
    # LLM
    "LLMPort",
    "LLMConfig",
    "LLMResponse",
    # Embedding
    "EmbeddingPort",
    "EmbeddingResult",
    # Knowledge Graph
    "KnowledgeGraphPort",
    # Clock
    "ClockPort",
    "SystemClock",
    # ID Generator
    "IdGeneratorPort",
    "UUIDGenerator",
    "DeterministicIdGenerator",
    # Google Calendar
    "GoogleCalendarPort",
    "GoogleCalendarInfo",
    "GoogleUserInfo",
    "OAuthTokens",
]
