"""Load and search internal documentation bundled with the agent system."""

import re
from importlib.resources import files
from pathlib import Path


DOC_FILES = [
    "getting-started.md",
    "chat-and-conversations.md",
    "groups-and-collaboration.md",
    "events-and-calendar.md",
    "memory-and-knowledge.md",
    "tools-and-capabilities.md",
    "settings-and-account.md",
    "knowledge-graph-reference.md",
    "evals-and-tracing.md",
]


def load_internal_docs() -> str:
    """Load all internal documentation as a single string.

    Returns:
        Concatenated content of all doc files, or empty string if not found.
    """
    parts: list[str] = []
    try:
        pkg = files("agent_system.docs")
        for name in DOC_FILES:
            path = pkg / name
            if path.is_file():
                parts.append(path.read_text(encoding="utf-8"))
    except Exception:
        # Fallback: try path relative to package root (e.g. when running from source)
        try:
            pkg_root = Path(__file__).resolve().parent
            for name in DOC_FILES:
                path = pkg_root / name
                if path.is_file():
                    parts.append(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return "\n\n---\n\n".join(parts) if parts else ""


def _split_into_sections(content: str) -> list[tuple[str, str]]:
    """Split markdown content into (title, body) sections by ## headers."""
    sections: list[tuple[str, str]] = []
    pattern = re.compile(r"^## (.+)$", re.MULTILINE)
    matches = list(pattern.finditer(content))

    for i, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        sections.append((title, body))
    return sections


def _relevance_score(query_terms: list[str], text: str) -> float:
    """Compute keyword relevance score: count of query terms in text (case-insensitive)."""
    text_lower = text.lower()
    score = 0.0
    for term in query_terms:
        if len(term) < 2:
            continue
        # Count occurrences, with bonus for word boundaries
        count = len(re.findall(rf"\b{re.escape(term)}\b", text_lower, re.IGNORECASE))
        if count > 0:
            score += 1.0 + min(count * 0.2, 2.0)  # Cap per-term boost
    return score


def search_internal_docs(query: str, max_sections: int = 5) -> list[dict[str, str | float]]:
    """Search internal documentation for sections relevant to the query.

    Uses keyword matching: splits docs by ## headers and scores each section
    by how many query terms appear in it.

    Args:
        query: Search query (e.g. "how does semantic search work")
        max_sections: Maximum number of sections to return

    Returns:
        List of dicts with keys: title (str), content (str), relevance (float).
        Sorted by relevance descending.
    """
    content = load_internal_docs()
    if not content:
        return []

    query_terms = [t.lower() for t in query.split() if len(t) >= 2]
    if not query_terms:
        # No meaningful terms - return first few sections
        sections = _split_into_sections(content)
        return [
            {"title": title, "content": body[:2000], "relevance": 0.0}
            for title, body in sections[:max_sections]
        ]

    sections = _split_into_sections(content)
    scored: list[tuple[float, str, str]] = []
    for title, body in sections:
        score = _relevance_score(query_terms, title) * 2.0 + _relevance_score(
            query_terms, body
        )
        scored.append((score, title, body))

    scored.sort(key=lambda x: x[0], reverse=True)

    results: list[dict[str, str | float]] = []
    for score, title, body in scored[:max_sections]:
        if score > 0 or len(results) < 2:  # Include at least 2 even with low score
            # Truncate long sections
            content_preview = body[:3000] + ("..." if len(body) > 3000 else "")
            results.append(
                {"title": title, "content": content_preview, "relevance": round(score, 2)}
            )
    return results
