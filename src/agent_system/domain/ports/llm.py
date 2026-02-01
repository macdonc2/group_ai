"""LLM port interface for language model interactions."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from agent_system.domain.value_objects import Message


@dataclass
class LLMResponse:
    """Response from an LLM call."""

    content: str
    tool_calls: list[dict[str, Any]]
    usage: dict[str, int]
    model: str
    finish_reason: str


@dataclass
class LLMConfig:
    """Configuration for LLM calls."""

    model: str = "openai:gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 4096
    system_prompt: str | None = None


class LLMPort(ABC):
    """Port interface for LLM interactions."""

    @abstractmethod
    async def generate(
        self,
        messages: list[Message],
        config: LLMConfig | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Generate a response from the LLM.
        
        Args:
            messages: Conversation history
            config: LLM configuration
            tools: Available tools for the LLM to call
            
        Returns:
            LLM response with content and optional tool calls
        """
        ...

    @abstractmethod
    async def generate_structured(
        self,
        messages: list[Message],
        output_schema: type[Any],
        config: LLMConfig | None = None,
    ) -> Any:
        """Generate a structured response from the LLM.
        
        Args:
            messages: Conversation history
            output_schema: Pydantic model for structured output
            config: LLM configuration
            
        Returns:
            Parsed structured output
        """
        ...

    @abstractmethod
    async def count_tokens(self, messages: list[Message]) -> int:
        """Count tokens in messages.
        
        Args:
            messages: Messages to count tokens for
            
        Returns:
            Token count
        """
        ...
