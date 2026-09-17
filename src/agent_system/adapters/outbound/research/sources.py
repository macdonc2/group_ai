"""Source adapters for the research lanes.

All are keyless by default. Rate limits are modest, so the lanes issue a
handful of queries each, not dozens. Every function is fail-soft: a failed
call returns an empty list and the lane carries on.
"""

from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from html import unescape

import httpx

from agent_system.domain.entities.research import Lane, Source

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(20.0, connect=10.0)
USER_AGENT = "agent-system-deep-research/1.0 (+https://agent.macdonml.com)"
SNIPPET_CHARS = 1500
PAGE_CHARS = 8000


def _clip(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


# ---------------------------------------------------------------------------
# arXiv (Atom API, no key)
# ---------------------------------------------------------------------------

_ATOM = "{http://www.w3.org/2005/Atom}"


async def search_arxiv(query: str, max_results: int = 8) -> list[Source]:
    url = "https://export.arxiv.org/api/query"
    params = {
        "search_query": f"all:{query}",
        "max_results": max_results,
        "sortBy": "relevance",
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
        return parse_arxiv_atom(r.text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("arXiv search failed for %r: %s", query, exc)
        return []


def parse_arxiv_atom(xml_text: str) -> list[Source]:
    out: list[Source] = []
    root = ET.fromstring(xml_text)
    for entry in root.findall(f"{_ATOM}entry"):
        title = _clip(entry.findtext(f"{_ATOM}title") or "", 300)
        summary = _clip(entry.findtext(f"{_ATOM}summary") or "", SNIPPET_CHARS)
        link = entry.findtext(f"{_ATOM}id") or None
        published = entry.findtext(f"{_ATOM}published") or ""
        year = int(published[:4]) if published[:4].isdigit() else None
        authors = [
            (a.findtext(f"{_ATOM}name") or "").strip()
            for a in entry.findall(f"{_ATOM}author")
        ][:6]
        if title:
            out.append(
                Source(id="", lane="academic", title=title, url=link, authors=authors,
                       year=year, venue="arXiv", snippet=summary)
            )
    return out


# ---------------------------------------------------------------------------
# Semantic Scholar (Graph API; key optional)
# ---------------------------------------------------------------------------

async def search_semantic_scholar(query: str, max_results: int = 8, api_key: str | None = None) -> list[Source]:
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": query,
        "limit": max_results,
        "fields": "title,abstract,year,authors,venue,url,citationCount,externalIds",
    }
    headers = {"User-Agent": USER_AGENT}
    if api_key:
        headers["x-api-key"] = api_key
    # Unauthenticated S2 allows roughly one request per second; back off on 429.
    delays = (0.0, 1.5, 3.0, 6.0)
    for attempt, delay in enumerate(delays):
        if delay:
            await asyncio.sleep(delay)
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers) as client:
                r = await client.get(url, params=params)
            if r.status_code == 429 and attempt < len(delays) - 1:
                continue
            r.raise_for_status()
            return parse_semantic_scholar(r.json())
        except Exception as exc:  # noqa: BLE001
            if attempt == len(delays) - 1:
                logger.warning("Semantic Scholar search failed for %r: %s", query, exc)
    return []


async def search_semantic_scholar_many(queries: list[str], max_results: int = 8, api_key: str | None = None) -> list[Source]:
    """Sequential, spaced queries so the unauthenticated rate limit holds."""
    out: list[Source] = []
    for i, q in enumerate(queries):
        if i:
            await asyncio.sleep(1.2)
        out.extend(await search_semantic_scholar(q, max_results, api_key))
    return out


def parse_semantic_scholar(payload: dict) -> list[Source]:
    out: list[Source] = []
    for p in payload.get("data", []) or []:
        title = _clip(p.get("title") or "", 300)
        if not title:
            continue
        ext = p.get("externalIds") or {}
        url = p.get("url")
        if ext.get("ArXiv"):
            url = f"https://arxiv.org/abs/{ext['ArXiv']}"
        elif ext.get("DOI"):
            url = f"https://doi.org/{ext['DOI']}"
        out.append(
            Source(
                id="", lane="academic", title=title, url=url,
                authors=[a.get("name", "") for a in (p.get("authors") or [])][:6],
                year=p.get("year"), venue=p.get("venue") or "Semantic Scholar",
                snippet=_clip(p.get("abstract") or "", SNIPPET_CHARS),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Web (DuckDuckGo via the existing tool) and page fetch
# ---------------------------------------------------------------------------

async def search_web(query: str, max_results: int = 6) -> list[Source]:
    from agent_system.adapters.outbound.llm.tools import web_search

    try:
        result = await web_search(query, num_results=max_results)
    except Exception as exc:  # noqa: BLE001
        logger.warning("web search failed for %r: %s", query, exc)
        return []
    if not result.success or not result.data:
        return []
    out: list[Source] = []
    for r in result.data:
        url = r.get("url") or ""
        if not url:
            continue
        host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
        out.append(
            Source(id="", lane="practical", title=_clip(r.get("title") or host, 300),
                   url=url, venue=host, snippet=_clip(r.get("snippet") or "", SNIPPET_CHARS))
        )
    return out


_TAG_RE = re.compile(r"<[^>]+>")
_DROP_RE = re.compile(r"<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>", re.S | re.I)


def html_to_text(html: str) -> str:
    """Readable text from HTML. BeautifulSoup when available, regex fallback."""
    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form"]):
            tag.decompose()
        main = soup.find("main") or soup.find("article") or soup.body or soup
        text = main.get_text(" ", strip=True)
    except Exception:  # noqa: BLE001
        text = unescape(_TAG_RE.sub(" ", _DROP_RE.sub(" ", html)))
    return re.sub(r"\s+", " ", text).strip()


async def fetch_readable(url: str, max_chars: int = PAGE_CHARS) -> str:
    """Page text for the practical/empirical lanes. PDFs and binaries are skipped."""
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client:
            r = await client.get(url)
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            if "html" not in ctype and "text" not in ctype:
                return ""
            return html_to_text(r.text)[:max_chars]
    except Exception as exc:  # noqa: BLE001
        logger.info("fetch failed for %s: %s", url, exc)
        return ""


# ---------------------------------------------------------------------------
# GitHub (search API; token optional)
# ---------------------------------------------------------------------------

async def search_github(query: str, max_results: int = 5, token: str | None = None) -> list[Source]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers) as client:
            r = await client.get(
                "https://api.github.com/search/repositories",
                params={"q": query, "sort": "stars", "order": "desc", "per_page": max_results},
            )
            r.raise_for_status()
            items = r.json().get("items", [])
            out: list[Source] = []
            for it in items:
                full = it.get("full_name", "")
                desc = it.get("description") or ""
                stars = it.get("stargazers_count", 0)
                readme = ""
                try:
                    rr = await client.get(
                        f"https://raw.githubusercontent.com/{full}/HEAD/README.md"
                    )
                    if rr.status_code == 200:
                        readme = _clip(rr.text, SNIPPET_CHARS)
                except Exception:  # noqa: BLE001
                    pass
                out.append(
                    Source(
                        id="", lane="practical", title=f"{full} ({stars:,} stars)",
                        url=it.get("html_url"), venue="GitHub",
                        snippet=_clip(f"{desc} — {readme}", SNIPPET_CHARS),
                    )
                )
            return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("GitHub search failed for %r: %s", query, exc)
        return []


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def dedupe(sources: list[Source]) -> list[Source]:
    seen: set[str] = set()
    out: list[Source] = []
    for s in sources:
        key = (s.url or "").rstrip("/").lower() or re.sub(r"\W+", "", s.title.lower())[:80]
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def assign_ids(sources: list[Source], lane: Lane) -> list[Source]:
    prefix = {"academic": "A", "practical": "P", "empirical": "E"}[lane]
    out = []
    for i, s in enumerate(sources, 1):
        out.append(s.model_copy(update={"id": f"{prefix}{i}", "lane": lane}))
    return out


async def gather_soft(*coros):
    """asyncio.gather that turns exceptions into empty lists."""
    results = await asyncio.gather(*coros, return_exceptions=True)
    return [[] if isinstance(r, BaseException) else r for r in results]
