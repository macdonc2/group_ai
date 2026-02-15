"""Application configuration using Pydantic Settings."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # OpenAI Configuration (optional - users provide their own keys via Settings)
    openai_api_key: str | None = Field(default=None, description="System-wide OpenAI API key (optional - users provide their own)")

    # Neo4j Configuration
    neo4j_uri: str = Field(default="bolt://localhost:7687", description="Neo4j connection URI")
    neo4j_user: str = Field(default="neo4j", description="Neo4j username")
    neo4j_password: str = Field(default="password", description="Neo4j password")

    # Database Configuration
    database_url: str = Field(
        default="sqlite+aiosqlite:///./agent_system.db",
        description="SQLAlchemy database URL",
    )

    # Application Configuration
    debug: bool = Field(default=False, description="Enable debug mode")
    secret_key: str = Field(
        default="change-me-in-production",
        description="Secret key for JWT tokens",
    )

    # API Configuration
    api_host: str = Field(default="0.0.0.0", description="API host")
    api_port: int = Field(default=8000, description="API port")

    # Agent Configuration
    default_model: str = Field(
        default="openai:gpt-5.2-2025-12-11",
        description="Default LLM model",
    )
    fallback_model: str = Field(
        default="openai:gpt-5-mini-2025-08-07",
        description="Fallback LLM model for intent/utility when primary fails",
    )
    max_tokens: int = Field(default=4096, description="Maximum tokens for LLM responses")
    temperature: float = Field(default=0.7, description="LLM temperature")

    # Google Calendar Configuration
    google_client_id: str | None = Field(default=None, description="Google OAuth Client ID")
    google_client_secret: str | None = Field(default=None, description="Google OAuth Client Secret")
    google_redirect_uri: str = Field(
        default="http://localhost:8000/api/calendar/callback",
        description="Google OAuth redirect URI",
    )


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()
