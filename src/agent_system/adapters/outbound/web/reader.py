"""Read web pages for the chat agent.

`read_page(url)` returns the readable text of a page:

1. robots.txt is honored (a page the site disallows for bots is not fetched).
2. A plain HTTP fetch is tried first; most pages work this way.
3. When the HTML is a JavaScript shell (little text, or "enable JavaScript"),
   the page is rendered in headless Chromium via Playwright, if installed and
   enabled (`WEB_JS_RENDER`).

The reader identifies itself honestly and does not try to get around bot
protection: a 401/403/429 or a challenge page is reported as `blocked`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from agent_system.adapters.outbound.research.sources import html_to_text

logger = logging.getLogger(__name__)

USER_AGENT = "agent-system-reader/1.0 (+https://agent.macdonml.com)"
ROBOTS_AGENT = "agent-system-reader"
TIMEOUT = httpx.Timeout(12.0, connect=6.0)
THIN_TEXT = 400  # fewer readable chars than this suggests a JS-rendered page
_JS_HINTS = re.compile(
    r"enable javascript|javascript is (required|disabled)|requires javascript|scripts did not run|"
    r"you need to enable javascript|this app works best with javascript",
    re.I,
)
_CHALLENGE_HINTS = re.compile(r"just a moment|checking your browser|attention required|verify you are human|captcha", re.I)


@dataclass
class PageResult:
    url: str
    text: str
    status: str  # ok | rendered | blocked | disallowed | unavailable | empty | error | skipped
    detail: str = ""


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------

_robots: dict[str, tuple[float, RobotFileParser | None]] = {}
_ROBOTS_TTL = 3600.0


async def _allowed(client: httpx.AsyncClient, url: str) -> bool:
    parts = urlparse(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    cached = _robots.get(origin)
    if cached is None or time.monotonic() - cached[0] > _ROBOTS_TTL:
        parser: RobotFileParser | None = None
        try:
            r = await client.get(f"{origin}/robots.txt", timeout=httpx.Timeout(5.0))
            if r.status_code == 200:
                parser = RobotFileParser()
                parser.parse(r.text.splitlines())
        except Exception:  # noqa: BLE001 - unreachable robots.txt means no rules
            parser = None
        _robots[origin] = (time.monotonic(), parser)
        cached = _robots[origin]
    parser = cached[1]
    return True if parser is None else parser.can_fetch(ROBOTS_AGENT, url)


# ---------------------------------------------------------------------------
# JS rendering (optional)
# ---------------------------------------------------------------------------

_browser = None
_playwright = None  # keep the driver alive for the browser's lifetime
_browser_lock = asyncio.Lock()
_render_slots = asyncio.Semaphore(2)


def _js_render_enabled() -> bool:
    from agent_system.composition_root.config import get_settings

    if not get_settings().web_js_render:
        return False
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


async def _get_browser():
    global _browser, _playwright
    async with _browser_lock:
        if _browser is None or not _browser.is_connected():
            from playwright.async_api import async_playwright

            if _playwright is None:
                _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        return _browser


async def _render(url: str, max_chars: int) -> PageResult:
    async with _render_slots:
        browser = await _get_browser()
        context = await browser.new_context(user_agent=USER_AGENT, java_script_enabled=True)
        try:
            page = await context.new_page()
            # Images, fonts and media aren't needed for text.
            await page.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in {"image", "media", "font"}
                else route.continue_(),
            )
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            if resp is not None and resp.status in (401, 403, 429):
                return PageResult(url, "", "blocked", f"HTTP {resp.status}")
            with contextlib.suppress(Exception):  # busy pages never go idle; use what's there
                await page.wait_for_load_state("networkidle", timeout=6000)
            text = re.sub(r"\s+", " ", await page.inner_text("body")).strip()
            if _CHALLENGE_HINTS.search(text[:600]) and len(text) < 1500:
                return PageResult(url, "", "blocked", "bot challenge page")
            return PageResult(url, text[:max_chars], "rendered" if text else "empty")
        finally:
            await context.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def read_page(url: str, max_chars: int = 6000, allow_render: bool = True) -> PageResult:
    """Readable text of `url`, or a status saying why there isn't any. Never raises."""
    if not url or not url.startswith(("http://", "https://")):
        return PageResult(url, "", "skipped", "not an http(s) URL")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
            if not await _allowed(client, url):
                return PageResult(url, "", "disallowed", "robots.txt disallows this page")
            r = await client.get(url)
            if r.status_code in (401, 403, 429):
                return PageResult(url, "", "blocked", f"HTTP {r.status_code}")
            if r.status_code in (502, 503, 504):  # often "no automated queries"; not retried around
                return PageResult(url, "", "unavailable", f"HTTP {r.status_code}")
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            if "html" not in ctype and "text" not in ctype:
                return PageResult(url, "", "skipped", f"not a web page ({ctype.split(';')[0] or 'unknown type'})")
            text = html_to_text(r.text)
            if _CHALLENGE_HINTS.search(text[:600]) and len(text) < 1500:
                return PageResult(url, "", "blocked", "bot challenge page")
            needs_js = len(text) < THIN_TEXT or bool(_JS_HINTS.search(text[:2000]))
            if needs_js and allow_render and _js_render_enabled():
                try:
                    rendered = await _render(url, max_chars)
                    if rendered.text or rendered.status == "blocked":
                        return rendered
                except Exception as exc:  # noqa: BLE001
                    logger.info("render failed for %s: %s", url, exc)
            return PageResult(url, text[:max_chars], "ok" if text else "empty")
    except Exception as exc:  # noqa: BLE001
        return PageResult(url, "", "error", f"{type(exc).__name__}: {str(exc)[:120]}")


async def read_pages(urls: list[str], max_chars: int = 3000, budget_s: float = 20.0) -> list[PageResult]:
    """Read several pages concurrently within an overall time budget."""
    tasks = [asyncio.create_task(read_page(u, max_chars)) for u in urls]
    done, pending = await asyncio.wait(tasks, timeout=budget_s)
    for t in pending:
        t.cancel()
    out = []
    for u, t in zip(urls, tasks, strict=True):
        if t in done and not t.cancelled() and t.exception() is None:
            out.append(t.result())
        else:
            out.append(PageResult(u, "", "error", "timed out"))
    return out
