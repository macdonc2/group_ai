"""Composition root - Dependency injection and application factory."""

from agent_system.composition_root.config import Settings, get_settings
from agent_system.composition_root.container import (
    Container,
    get_container,
    shutdown_container,
)
from agent_system.composition_root.services import (
    AgentService,
    PlanService,
    UserService,
)

__all__ = [
    # Config
    "Settings",
    "get_settings",
    # Container
    "Container",
    "get_container",
    "shutdown_container",
    # Services
    "AgentService",
    "PlanService",
    "UserService",
]
