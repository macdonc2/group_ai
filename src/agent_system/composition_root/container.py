"""Dependency injection container."""

import asyncio
from dataclasses import dataclass
from typing import Any

from agent_system.adapters.outbound.calendar import GoogleCalendarAdapter
from agent_system.adapters.outbound.embedding import OpenAIEmbeddingAdapter
from agent_system.adapters.outbound.graph import Neo4jAdapter
from agent_system.adapters.outbound.llm import OpenAIAdapter
from agent_system.adapters.outbound.persistence import Database
from agent_system.composition_root.config import Settings
from agent_system.domain.ports import (
    EmbeddingPort,
    GoogleCalendarPort,
    KnowledgeGraphPort,
    LLMPort,
)

# Longest the graph index checks may take while the container is being built.
GRAPH_SETUP_TIMEOUT_S = 15.0


@dataclass
class Container:
    """Dependency injection container.
    
    This container holds the configured long-lived adapters.
    """

    settings: Settings
    database: Database
    llm_adapter: LLMPort | None
    knowledge_graph_adapter: KnowledgeGraphPort | None
    embedding_adapter: EmbeddingPort | None
    google_calendar_adapter: GoogleCalendarPort | None

    @classmethod
    async def create(cls, settings: Settings | None = None) -> "Container":
        """Create and initialize the container.
        
        Args:
            settings: Application settings. Loads from environment if None.
            
        Returns:
            Initialized container
        """
        from agent_system.composition_root.config import get_settings
        
        settings = settings or get_settings()
        
        # Create database
        database = Database(settings.database_url, echo=settings.debug)
        await database.create_tables()
        
        # Create LLM adapter (optional - requires API key)
        # With per-user API keys, this may not be needed at container level
        llm_adapter: LLMPort | None = None
        if settings.openai_api_key:
            try:
                llm_adapter = OpenAIAdapter(
                    api_key=settings.openai_api_key,
                    default_model=settings.default_model,
                )
                print("✓ LLM adapter initialized (system API key)")
            except Exception as e:
                print(f"✗ LLM adapter initialization failed: {e}")
        else:
            print("ℹ No system OpenAI API key - using per-user keys only")
        
        # Create knowledge graph adapter (optional - may not be available)
        knowledge_graph_adapter: KnowledgeGraphPort | None = None
        try:
            neo4j_adapter = Neo4jAdapter(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
            )
            await neo4j_adapter.connect()
            knowledge_graph_adapter = neo4j_adapter
            print(f"✓ Neo4j connected: {settings.neo4j_uri}")
        except Exception as e:
            # Neo4j not available - continue without it
            print(f"✗ Neo4j connection failed: {e}")
            pass
        
        # Create embedding adapter for semantic search (requires API key)
        embedding_adapter: EmbeddingPort | None = None
        if settings.openai_api_key:
            try:
                embedding_adapter = OpenAIEmbeddingAdapter(
                    api_key=settings.openai_api_key,
                )
                print("✓ Embedding adapter initialized (text-embedding-3-small)")
                
                # Set up vector index if Neo4j is available
                if knowledge_graph_adapter:
                    # Bounded: this now runs while the app starts, and a graph store that
                    # does not answer must not keep the app from starting.
                    await asyncio.wait_for(
                        knowledge_graph_adapter.ensure_vector_index(
                            dimensions=embedding_adapter.get_dimensions()
                        ),
                        GRAPH_SETUP_TIMEOUT_S,
                    )
                    print("✓ Neo4j vector index ready")
                    
                    # Set up temporal indexes for time-based queries
                    await asyncio.wait_for(
                        knowledge_graph_adapter.ensure_temporal_index(), GRAPH_SETUP_TIMEOUT_S
                    )
                    print("✓ Neo4j temporal indexes ready")
            except Exception as e:
                print(f"✗ Embedding adapter initialization failed: {e}")
        else:
            print("ℹ Embedding adapter skipped - no system API key")
        
        # Create Google Calendar adapter (optional - requires OAuth credentials)
        google_calendar_adapter: GoogleCalendarPort | None = None
        if settings.google_client_id and settings.google_client_secret:
            try:
                google_calendar_adapter = GoogleCalendarAdapter(
                    client_id=settings.google_client_id,
                    client_secret=settings.google_client_secret,
                    redirect_uri=settings.google_redirect_uri,
                )
                print("✓ Google Calendar adapter initialized")
            except Exception as e:
                print(f"✗ Google Calendar adapter initialization failed: {e}")
        else:
            print("ℹ Google Calendar adapter skipped - no OAuth credentials")
        
        return cls(
            settings=settings,
            database=database,
            llm_adapter=llm_adapter,
            knowledge_graph_adapter=knowledge_graph_adapter,
            embedding_adapter=embedding_adapter,
            google_calendar_adapter=google_calendar_adapter,
        )

    async def close(self) -> None:
        """Clean up resources."""
        await self.database.dispose()
        if self.knowledge_graph_adapter and isinstance(self.knowledge_graph_adapter, Neo4jAdapter):
            await self.knowledge_graph_adapter.close()


# Global container instance
_container: Container | None = None
print(f"=== container.py module loaded, _container={_container} ===")


def set_container(container: Container | None) -> None:
    """Make `container` the one `get_container()` returns, or clear it with None.

    The API builds its container once at startup (`create_app`'s lifespan) and registers it
    here, so code that still asks for the container by calling `get_container()` gets the
    same objects as the rest of the app instead of building a second set.
    """
    global _container
    _container = container


async def get_container() -> Container:
    """Get the global container instance.

    Inside the API this is the container the app built at startup. Elsewhere (the eval
    command line, scripts) nothing has registered one, so it is created on first access.

    Returns:
        The container instance
    """
    global _container
    if _container is None:
        print(f"=== Creating new container (was None) ===")
        _container = await Container.create()
    else:
        print(f"=== Using existing container ===")
    return _container


async def shutdown_container() -> None:
    """Shutdown and clean up the global container."""
    global _container
    if _container is not None:
        await _container.close()
        _container = None
