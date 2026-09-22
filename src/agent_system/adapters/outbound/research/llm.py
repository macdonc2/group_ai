"""Model construction for the research pipeline.

Keys are passed explicitly (never via os.environ) because runs happen in a
background task, possibly for several users at once.
"""

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIResponsesModel

from agent_system.adapters.outbound.llm.provider import openai_provider


def model_name(model_string: str) -> str:
    """'openai:gpt-6-astra' -> 'gpt-6-astra'."""
    return model_string.split(":", 1)[1] if ":" in model_string else model_string


def make_model(model_string: str, api_key: str) -> OpenAIResponsesModel:
    # GPT-5.6/6 reject function tools (which structured output relies on) over
    # Chat Completions unless reasoning is disabled; the Responses API allows both.
    return OpenAIResponsesModel(model_name(model_string), provider=openai_provider(api_key, long_running=True))


def make_agent(model_string: str, api_key: str, system_prompt: str, output_type=str, retries: int = 2) -> Agent:
    return Agent(
        model=make_model(model_string, api_key),
        system_prompt=system_prompt,
        output_type=output_type,
        retries=retries,
    )
