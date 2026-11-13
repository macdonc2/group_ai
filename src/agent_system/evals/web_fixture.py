"""Canned web content for eval cases.

A case with `web_fixture` gets that text back from `web_search` and `read_webpage` instead of
the live web, so prompt-injection cases are deterministic and never fetch anything. The hook
is installed only in eval processes and falls through to the real tools when no fixture is set.
"""

from __future__ import annotations

import contextvars

_fixture: contextvars.ContextVar[str | None] = contextvars.ContextVar("eval_web_fixture", default=None)
_installed = False


def set_web_fixture(text: str | None) -> contextvars.Token:
    return _fixture.set(text)


def reset_web_fixture(token: contextvars.Token) -> None:
    _fixture.reset(token)


def install_web_fixture_hook() -> None:
    """Wrap the two web tools once; both engines look them up through `tools.py`."""
    global _installed
    if _installed:
        return
    from agent_system.adapters.outbound.llm import tools

    real_search, real_read = tools.web_search, tools.read_webpage

    async def web_search(query: str, num_results: int = 5) -> tools.ToolResult:
        text = _fixture.get()
        if text is None:
            return await real_search(query, num_results)
        item = {"title": "Eval fixture page", "url": "https://fixture.example/page",
                "snippet": text[:200], "page_text": text}
        return tools.ToolResult(success=True, data=[item], message="Found 1 result")

    async def read_webpage(url: str) -> tools.ToolResult:
        text = _fixture.get()
        if text is None:
            return await real_read(url)
        return tools.ToolResult(success=True, data={"url": url, "text": text, "status": "ok"},
                                message=f"Page fetched: {url}\n\n{text}")

    tools.web_search, tools.read_webpage = web_search, read_webpage
    tools.AVAILABLE_TOOLS["web_search"]["function"] = web_search
    tools.AVAILABLE_TOOLS["read_webpage"]["function"] = read_webpage
    _installed = True
