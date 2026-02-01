"""FastAPI REST API adapter."""

from agent_system.adapters.inbound.api.main import app, create_app

__all__ = [
    "app",
    "create_app",
]
