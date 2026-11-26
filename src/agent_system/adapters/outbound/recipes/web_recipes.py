"""Look recipes up on the web: search, fetch the pages, read their structured recipe data.

Three steps, and only the first involves anything like judgement (a search engine's ranking):

1. `ddgs` text search for "<query> recipe".
2. Each result page is fetched with the app's guarded reader rules: public addresses only
   (`url_guard`), robots.txt honoured, an honest User-Agent, no attempt to get past a block.
3. `domain/recipes/jsonld.py` reads the page's own schema.org Recipe data into a `Recipe`.

A page that blocks us, or that does not publish structured recipe data, is skipped. No model
reads the page, so nothing on it can instruct a model, and nothing is paraphrased.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from agent_system.adapters.outbound.web.reader import TIMEOUT, USER_AGENT, _allowed
from agent_system.adapters.outbound.web.url_guard import BlockedURL, guarded_client
from agent_system.domain.recipes.jsonld import recipes_from_html
from agent_system.domain.recipes.models import Recipe

logger = logging.getLogger(__name__)

MAX_PAGE_BYTES = 3_000_000
MAX_PAGES = 6


class WebRecipeError(Exception):
    """Why a page gave no recipe, in words fit to show the person."""


async def fetch_recipes(url: str) -> list[Recipe]:
    """The recipes a page declares. Raises `WebRecipeError` with the reason when there are none."""
    url = url.strip()
    if not url.startswith(("http://", "https://")) or len(url) > 2000 or any(ch.isspace() for ch in url):
        raise WebRecipeError("That is not a web address.")
    try:
        async with guarded_client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
            if not await _allowed(client, url):
                raise WebRecipeError("That site asks automated readers not to read this page.")
            async with client.stream("GET", url) as response:
                if response.status_code in (401, 403, 429):
                    raise WebRecipeError("That site blocks automated readers.")
                if response.status_code >= 400:
                    raise WebRecipeError(f"The site answered with an error ({response.status_code}).")
                if "html" not in response.headers.get("content-type", ""):
                    raise WebRecipeError("That address is not a web page.")
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_PAGE_BYTES:
                        break
                    chunks.append(chunk)
                final_url = str(response.url)
                page = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
    except BlockedURL:
        logger.warning("recipe fetch refused: not a public address", extra={"event": "ssrf_blocked"})
        raise WebRecipeError("That is not a public web address.") from None
    except httpx.HTTPError as exc:
        raise WebRecipeError(f"The page could not be fetched ({type(exc).__name__}).") from None
    found = recipes_from_html(page, final_url)
    if not found:
        raise WebRecipeError("That page does not publish its recipe in a form the app can read exactly.")
    return found


def _search_sync(query: str, limit: int) -> list[str]:
    from ddgs import DDGS

    with DDGS() as engine:
        results = list(engine.text(f"{query} recipe", max_results=limit))
    urls = [str(r.get("href") or r.get("link") or "") for r in results]
    return [u for u in dict.fromkeys(urls) if u.startswith(("http://", "https://"))]


async def search_urls(query: str, limit: int = MAX_PAGES) -> list[str]:
    """Result addresses for a recipe search (a seam for tests)."""
    return await asyncio.get_running_loop().run_in_executor(None, _search_sync, query[:200], limit)


async def search_recipes(query: str, *, limit: int = 4, budget_s: float = 20.0) -> list[Recipe]:
    """Up to `limit` recipes from the web for `query`, read from the pages' own recipe data.
    Never raises: a failed search or page simply contributes nothing."""
    try:
        urls = await search_urls(query)
    except Exception as exc:  # noqa: BLE001 - the search engine being down is "found nothing"
        logger.warning("recipe web search failed: %s: %s", type(exc).__name__, exc)
        return []
    tasks = [asyncio.create_task(fetch_recipes(u)) for u in urls[:MAX_PAGES]]
    if not tasks:
        return []
    done, pending = await asyncio.wait(tasks, timeout=budget_s)
    for task in pending:
        task.cancel()
    found: list[Recipe] = []
    for task in tasks:                                         # keep the search engine's order
        if task in done and not task.cancelled() and task.exception() is None:
            for recipe in task.result()[:1]:
                if all(recipe.source_url != seen.source_url for seen in found):
                    found.append(recipe)
    return found[:limit]
