"""Persistence adapter - SQLAlchemy implementations."""

from agent_system.adapters.outbound.persistence.database import Base, Database
from agent_system.adapters.outbound.persistence.eval_models import (
    EvalCaseResultModel,
    EvalRunModel,
    TurnTraceModel,
)
from agent_system.adapters.outbound.persistence.group_repositories import (
    SQLAlchemyExtractedEventRepository,
    SQLAlchemyGroupConversationRepository,
    SQLAlchemyGroupRepository,
)
from agent_system.adapters.outbound.persistence.mappers import (
    ConversationMapper,
    ExtractedEventMapper,
    GroupConversationMapper,
    GroupMapper,
    GroupMembershipMapper,
    GroupMessageMapper,
    MessageMapper,
    PlanMapper,
    PlanStepMapper,
    UserMapper,
)
from agent_system.adapters.outbound.persistence.models import (
    ConversationModel,
    ExtractedEventModel,
    GroupConversationModel,
    GroupMembershipModel,
    GroupMessageModel,
    GroupModel,
    MessageModel,
    PlanModel,
    PlanStepModel,
    UserModel,
)
from agent_system.adapters.outbound.persistence.repositories import (
    SQLAlchemyConversationRepository,
    SQLAlchemyPlanRepository,
    SQLAlchemyUserRepository,
)
from agent_system.adapters.outbound.persistence.research_models import (
    ResearchAudioModel,
    ResearchFigureModel,
    ResearchJobModel,
)
from agent_system.adapters.outbound.persistence.research_repositories import (
    SQLAlchemyResearchRepository,
)

__all__ = [
    # Database
    "Base",
    "Database",
    # Models
    "UserModel",
    "ConversationModel",
    "MessageModel",
    "PlanModel",
    "PlanStepModel",
    "GroupModel",
    "GroupMembershipModel",
    "GroupConversationModel",
    "GroupMessageModel",
    "ExtractedEventModel",
    "ResearchJobModel",
    "ResearchFigureModel",
    "ResearchAudioModel",
    "TurnTraceModel",
    "EvalRunModel",
    "EvalCaseResultModel",
    # Mappers
    "UserMapper",
    "ConversationMapper",
    "MessageMapper",
    "PlanMapper",
    "PlanStepMapper",
    "GroupMapper",
    "GroupMembershipMapper",
    "GroupConversationMapper",
    "GroupMessageMapper",
    "ExtractedEventMapper",
    # Repositories
    "SQLAlchemyUserRepository",
    "SQLAlchemyConversationRepository",
    "SQLAlchemyPlanRepository",
    "SQLAlchemyGroupRepository",
    "SQLAlchemyGroupConversationRepository",
    "SQLAlchemyExtractedEventRepository",
    "SQLAlchemyResearchRepository",
]
