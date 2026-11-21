"""Canned web content for eval cases.

A case with `web_fixture` gets that text back from `web_search` and `read_webpage` instead of
the live web, so prompt-injection cases are deterministic and never fetch anything.

`web_tools(text)` returns replacement tool functions for one case. The eval runner hands
them to the turn (`AgentDependencies.tool_overrides`), so only that case's turns see them and
the real tool functions are never modified.
"""

from __future__ import annotations

from typing import Any

FIXTURE_URL = "https://fixture.example/page"


def web_tools(text: str | None) -> dict[str, Any]:
    """Stand-ins for the two web tools that return `text`; no stand-ins when there is none."""
    if text is None:
        return {}
    from agent_system.adapters.outbound.llm.tools import ToolResult

    async def web_search(query: str, num_results: int = 5) -> ToolResult:
        item = {"title": "Eval fixture page", "url": FIXTURE_URL, "snippet": text[:200], "page_text": text}
        return ToolResult(success=True, data=[item], message="Found 1 result")

    async def read_webpage(url: str) -> ToolResult:
        return ToolResult(success=True, data={"url": url, "text": text, "status": "ok"},
                          message=f"Page fetched: {url}\n\n{text}")

    return {"web_search": web_search, "read_webpage": read_webpage}
