"""FastAPI application factory."""

import logging
import os
import sys
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Configure logging for the application
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
# Set specific loggers to appropriate levels
logging.getLogger("agent_system").setLevel(logging.INFO)
logging.getLogger("uvicorn").setLevel(logging.INFO)

from agent_system.adapters.inbound.api.dependencies import set_database
from agent_system.adapters.inbound.api.routes import (
    agent_router,
    auth_router,
    calendar_router,
    conversations_router,
    groups_router,
    knowledge_router,
    plans_router,
    tools_router,
)
from agent_system.adapters.outbound.persistence import Database
from agent_system.composition_root.config import Settings, get_settings

# Load environment variables from .env file
# This ensures OPENAI_API_KEY is available for PydanticAI
load_dotenv()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application.
    
    Args:
        settings: Application settings. If None, loads from environment.
        
    Returns:
        Configured FastAPI application
    """
    settings = settings or get_settings()
    
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        """Application lifespan handler."""
        # Initialize database
        db = Database(settings.database_url, echo=settings.debug)
        await db.create_tables()
        set_database(db)
        
        yield
        
        # Cleanup
        await db.dispose()
    
    app = FastAPI(
        title="Agent System API",
        description="Hexagonal architecture agentic reasoning system with PydanticAI",
        version="0.1.0",
        lifespan=lifespan,
        debug=settings.debug,
    )
    
    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include routers
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(agent_router, prefix="/api/v1")
    app.include_router(calendar_router, prefix="/api/v1")
    app.include_router(conversations_router, prefix="/api/v1")
    app.include_router(groups_router, prefix="/api/v1")
    app.include_router(knowledge_router, prefix="/api/v1")
    app.include_router(plans_router, prefix="/api/v1")
    app.include_router(tools_router, prefix="/api/v1")
    
    @app.get("/health")
    async def health_check() -> dict[str, Any]:
        """Health check endpoint."""
        return {"status": "healthy", "version": "0.1.0"}
    
    @app.get("/")
    async def root() -> dict[str, Any]:
        """Root endpoint with API information."""
        return {
            "name": "Agent System API",
            "version": "0.1.0",
            "docs": "/docs",
            "health": "/health",
        }
    
    return app


# Default application instance
app = create_app()
