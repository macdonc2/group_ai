"""API routes package."""

from agent_system.adapters.inbound.api.routes.agent import router as agent_router
from agent_system.adapters.inbound.api.routes.auth import router as auth_router
from agent_system.adapters.inbound.api.routes.calendar import router as calendar_router
from agent_system.adapters.inbound.api.routes.conversations import router as conversations_router
from agent_system.adapters.inbound.api.routes.groups import router as groups_router
from agent_system.adapters.inbound.api.routes.knowledge import router as knowledge_router
from agent_system.adapters.inbound.api.routes.plans import router as plans_router
from agent_system.adapters.inbound.api.routes.tools import router as tools_router

__all__ = [
    "agent_router",
    "auth_router",
    "calendar_router",
    "conversations_router",
    "groups_router",
    "knowledge_router",
    "plans_router",
    "tools_router",
]
