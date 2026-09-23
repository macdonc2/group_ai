"""Page reading for web_search / read_webpage: robots.txt, blocks, JS fallback."""

import httpx
import pytest

from agent_system.adapters.outbound.fsm.nodes import format_web_results
from agent_system.adapters.outbound.web import reader

pytestmark = pytest.mark.unit

LONG = "<html><body><main>" + ("Real article text. " * 60) + "</main></body></html>"
SHELL = "<html><body><div id=root></div><noscript>You need to enable JavaScript to run this app.</noscript></body></html>"


def routes(request: httpx.Request) -> httpx.Response:
    host, path = request.url.host, request.url.path
    if path == "/robots.txt":
        body = "User-agent: *\nDisallow: /private\n" if host == "rules.test" else ""
        return httpx.Response(200 if body else 404, text=body)
    if host == "blocked.test":
        return httpx.Response(403, text="nope")
    if host == "busy.test":
        return httpx.Response(503, text="try later")
    if host == "spa.test":
        return httpx.Response(200, text=SHELL, headers={"content-type": "text/html"})
    if host == "pdf.test":
        return httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"})
    return httpx.Response(200, text=LONG, headers={"content-type": "text/html; charset=utf-8"})


@pytest.fixture(autouse=True)
def fake_http(monkeypatch):
    real = httpx.AsyncClient
    monkeypatch.setattr(reader.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(routes), **kw))
    reader._robots.clear()


async def test_plain_page_is_read():
    r = await reader.read_page("https://site.test/post")
    assert r.status == "ok" and "Real article text" in r.text


async def test_robots_disallow_is_honored():
    r = await reader.read_page("https://rules.test/private/page")
    assert r.status == "disallowed"
    assert (await reader.read_page("https://rules.test/public")).status == "ok"


async def test_blocks_and_unavailable_are_reported_not_evaded():
    assert (await reader.read_page("https://blocked.test/x")).status == "blocked"
    assert (await reader.read_page("https://busy.test/x")).status == "unavailable"


async def test_js_shell_falls_back_to_rendering(monkeypatch):
    monkeypatch.setattr(reader, "_js_render_enabled", lambda: True)

    async def fake_render(url, max_chars):
        return reader.PageResult(url, "Rendered content", "rendered")

    monkeypatch.setattr(reader, "_render", fake_render)
    r = await reader.read_page("https://spa.test/app")
    assert r.status == "rendered" and r.text == "Rendered content"


async def test_js_shell_without_renderer_returns_what_it_has(monkeypatch):
    monkeypatch.setattr(reader, "_js_render_enabled", lambda: False)
    r = await reader.read_page("https://spa.test/app")
    assert r.status == "empty" and r.text == ""  # an unrendered app shell has no readable text


async def test_non_html_is_skipped():
    assert (await reader.read_page("https://pdf.test/paper.pdf")).status == "skipped"


def test_format_web_results_includes_page_text_or_why_not():
    out = format_web_results([
        {"title": "Inventor page", "url": "https://a", "snippet": "s", "page_text": "Patent 1; Patent 2"},
        {"title": "Blocked", "url": "https://b", "snippet": "s2", "page_status": "blocked: HTTP 403"},
    ])
    assert "Page text (read from the site):\n  Patent 1; Patent 2" in out
    assert "(Page not read: blocked: HTTP 403)" in out
