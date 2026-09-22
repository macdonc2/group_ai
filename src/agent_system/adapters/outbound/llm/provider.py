"""OpenAI providers with explicit request timeouts.

The OpenAI SDK defaults to a 600 s timeout with 2 retries, so one stalled
request could hold a chat turn for up to half an hour (evals caught a single
coordinator call taking 618 s). Every model the app builds should get its
provider here.
"""

from __future__ import annotations

import httpx
from openai import AsyncOpenAI
from pydantic_ai.models import cached_async_http_client
from pydantic_ai.providers.openai import OpenAIProvider


def openai_provider(api_key: str, *, long_running: bool = False) -> OpenAIProvider:
    """Provider for chat-path calls, or `long_running=True` for Deep Research stages
    that legitimately think for minutes (the timeout applies between streamed chunks
    too, so streaming calls are only cut off when the stream itself stalls)."""
    from agent_system.composition_root.config import get_settings

    s = get_settings()
    seconds = s.research_request_timeout_s if long_running else s.llm_request_timeout_s
    timeout = httpx.Timeout(seconds, connect=10.0)
    http_client = cached_async_http_client(provider=f"openai:{int(seconds)}", timeout=int(seconds), connect=10)
    client = AsyncOpenAI(api_key=api_key, http_client=http_client, timeout=timeout, max_retries=s.llm_max_retries)
    return OpenAIProvider(openai_client=client)
