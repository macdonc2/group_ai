"""End-to-end API tests."""

import pytest
from httpx import ASGITransport, AsyncClient

from agent_system.adapters.inbound.api import create_app
from agent_system.composition_root.config import Settings


@pytest.fixture
def test_settings() -> Settings:
    """Create test settings."""
    return Settings(
        openai_api_key="test-key",
        database_url="sqlite+aiosqlite:///:memory:",
        debug=True,
    )


@pytest.fixture
def app(test_settings: Settings):
    """Create test application."""
    return create_app(test_settings)


@pytest.fixture
async def client(app):
    """Create test client with manual database setup."""
    from agent_system.adapters.inbound.api.dependencies import set_database
    from agent_system.adapters.outbound.persistence import Database
    
    # Manually set up database for testing
    db = Database("sqlite+aiosqlite:///:memory:", echo=False)
    await db.create_tables()
    set_database(db)
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    
    await db.dispose()


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    @pytest.mark.e2e
    async def test_health_check(self, client: AsyncClient):
        """Test health check returns OK."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


class TestRootEndpoint:
    """Tests for root endpoint."""

    @pytest.mark.e2e
    async def test_root_returns_api_info(self, client: AsyncClient):
        """Test root endpoint returns API info."""
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data


class TestConversationEndpoints:
    """Tests for conversation endpoints."""

    @pytest.mark.e2e
    async def test_create_conversation(self, client: AsyncClient):
        """Test creating a new conversation."""
        response = await client.post(
            "/api/v1/conversations",
            json={"title": "Test Conversation"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Test Conversation"
        assert "id" in data

    @pytest.mark.e2e
    async def test_list_conversations(self, client: AsyncClient):
        """Test listing conversations."""
        # Create a conversation first
        await client.post(
            "/api/v1/conversations",
            json={"title": "Test"},
        )
        
        response = await client.get("/api/v1/conversations")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestAgentEndpoints:
    """Tests for agent interaction endpoints."""

    @pytest.mark.e2e
    async def test_chat_creates_response(self, client: AsyncClient):
        """Test chat endpoint returns response."""
        response = await client.post(
            "/api/v1/agent/chat",
            json={"message": "Hello, how are you?"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "response" in data
        assert "conversation_id" in data
        assert "suggestions" in data


class TestPlanEndpoints:
    """Tests for plan endpoints."""

    @pytest.mark.e2e
    async def test_create_plan(self, client: AsyncClient):
        """Test creating a new plan."""
        response = await client.post(
            "/api/v1/plans",
            json={
                "goal_description": "Build a feature",
                "success_criteria": ["Feature works"],
                "steps": [
                    {"description": "Design"},
                    {"description": "Implement"},
                ],
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["goal_description"] == "Build a feature"
        assert len(data["steps"]) == 2

    @pytest.mark.e2e
    async def test_list_plans(self, client: AsyncClient):
        """Test listing plans."""
        response = await client.get("/api/v1/plans")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
