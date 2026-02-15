"""OpenAI LLM adapter implementing the LLM port."""

from typing import Any

from pydantic_ai import Agent

from agent_system.domain.ports import LLMConfig, LLMPort, LLMResponse
from agent_system.domain.value_objects import Message, MessageRole


class OpenAIAdapter(LLMPort):
    """OpenAI adapter using PydanticAI."""

    def __init__(self, api_key: str, default_model: str = "openai:gpt-5.2") -> None:
        """Initialize the OpenAI adapter.
        
        Args:
            api_key: OpenAI API key
            default_model: Default model to use
        """
        self._api_key = api_key
        self._default_model = default_model
        
        # Create a generic agent for standard generation
        self._generic_agent: Agent[None, str] = Agent(
            default_model,
            output_type=str,
        )

    def _convert_messages_to_prompt(self, messages: list[Message]) -> str:
        """Convert domain messages to a prompt string.
        
        Args:
            messages: List of domain messages
            
        Returns:
            Formatted prompt string
        """
        parts = []
        for msg in messages:
            role = msg.role.value.upper()
            content = msg.content.text
            parts.append(f"{role}: {content}")
        return "\n".join(parts)

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
            tools: Available tools (not yet implemented)
            
        Returns:
            LLM response with content
        """
        config = config or LLMConfig()
        model = config.model or self._default_model
        
        # Build prompt from messages
        prompt = self._convert_messages_to_prompt(messages)
        
        # Add system prompt if provided
        system_prompt = config.system_prompt or "You are a helpful AI assistant."
        
        # Create agent with configuration
        agent: Agent[None, str] = Agent(
            model,
            output_type=str,
            system_prompt=system_prompt,
        )
        
        # Run the agent
        result = await agent.run(prompt)
        
        return LLMResponse(
            content=result.output,
            tool_calls=[],
            usage={
                "prompt_tokens": 0,  # Would need to track actual usage
                "completion_tokens": 0,
                "total_tokens": 0,
            },
            model=model,
            finish_reason="stop",
        )

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
        config = config or LLMConfig()
        model = config.model or self._default_model
        
        # Build prompt from messages
        prompt = self._convert_messages_to_prompt(messages)
        
        # Add system prompt if provided
        system_prompt = config.system_prompt or "You are a helpful AI assistant."
        
        # Create agent with structured output
        agent = Agent(
            model,
            output_type=output_schema,
            system_prompt=system_prompt,
        )
        
        # Run the agent
        result = await agent.run(prompt)
        
        return result.output

    async def count_tokens(self, messages: list[Message]) -> int:
        """Count tokens in messages.
        
        Note: This is a rough estimate. For accurate counts,
        use the tiktoken library directly.
        
        Args:
            messages: Messages to count tokens for
            
        Returns:
            Estimated token count
        """
        # Rough estimate: ~4 characters per token
        total_chars = sum(len(msg.content.text) for msg in messages)
        return total_chars // 4
