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
        default="openai:gpt-6-astra",
        description="Default LLM model (chat, research lanes, synthesis, writing)",
    )
    fallback_model: str = Field(
        default="openai:gpt-5.6-luna",
        description="Cheap/fast model for intent, extraction, ranking and other structured steps",
    )

    # Deep Research
    tts_model: str = Field(default="gpt-4o-mini-tts", description="OpenAI text-to-speech model for report narration")
    tts_voice: str = Field(default="marin", description="TTS voice")
    semantic_scholar_api_key: str | None = Field(default=None, description="Optional: raises Semantic Scholar rate limits")
    github_token: str | None = Field(default=None, description="Optional: raises GitHub search rate limits")
    max_tokens: int = Field(default=4096, description="Maximum tokens for LLM responses")
    temperature: float = Field(default=0.7, description="LLM temperature")

    # LLM request limits (the SDK default is 600 s x 3 attempts)
    llm_request_timeout_s: float = Field(default=120, description="Per-request timeout for chat-path LLM calls")
    research_request_timeout_s: float = Field(default=600, description="Per-request timeout for Deep Research LLM calls")
    llm_max_retries: int = Field(default=1, description="Retries after a failed/timed-out LLM request")

    # Cost accounting: JSON map of model name -> USD per 1M tokens, e.g.
    # {"gpt-6-astra": {"input": 1.25, "cached_input": 0.125, "output": 10}}.
    # Used when genai-prices doesn't know a model; unpriced calls report cost as null.
    model_pricing_json: str = Field(default="{}", description="Per-model token prices (USD / 1M tokens)")

    # Evals
    eval_openai_api_key: str | None = Field(default=None, description="OpenAI key used by eval runs (system under test + OpenAI judge)")
    eval_judge_model: str = Field(default="openai:gpt-6-astra", description="Model for the OpenAI judge")
    jev_base_url: str | None = Field(default=None, description="OpenAI-compatible base URL for the Jev judge")
    jev_api_key: str | None = Field(default=None, description="API key for the Jev judge endpoint")
    jev_model: str = Field(default="jev", description="Model id served at jev_base_url")

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
