"""Typed, validated context for the model.

What a model is given decides what it says, so text does not go into a prompt as a loose
string or an untyped dictionary. It becomes a `Passage` first: a Pydantic model that says
what the text is, where it came from, whose it is and whether it can be trusted. A
`ContextBundle` collects the passages for one turn and applies the rules in code:

- a passage must have text, and web text must have a real http(s) address;
- web text can only exist as untrusted: the model refuses to be built any other way, so the
  marking does not depend on a call site remembering to wrap it;
- remembered text must belong to the current user;
- low-scoring and duplicate passages are dropped, and length is capped per passage and overall;
- text is cleaned of the markup the prompt uses for structure, so a page cannot close the
  untrusted block around itself.

A passage that breaks a rule is dropped and recorded with the reason. It never raises into
the turn: bad context should cost one passage, not the reply.

Only the bundle's renderers write this context into a prompt, and the bundle is recorded on
the turn's trace, so what the model saw can be inspected and tested afterwards.

After the reply, `check_reply` looks for links the reply gives that appear nowhere in what
the model was shown. It reports; it does not block.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SourceKind(StrEnum):
    WEB_SEARCH = "web_search"      # one search result, with the page's text when it was read
    WEB_PAGE = "web_page"          # a page the user or the model asked to open
    HISTORY = "history"            # something said in one of this user's earlier conversations


class Trust(StrEnum):
    TRUSTED = "trusted"            # written by the user or by the system
    UNTRUSTED = "untrusted"        # written by a third party: data, never instructions


UNTRUSTED_KINDS = frozenset({SourceKind.WEB_SEARCH, SourceKind.WEB_PAGE})
OWNED_KINDS = frozenset({SourceKind.HISTORY})

MAX_PASSAGE_CHARS = {SourceKind.WEB_SEARCH: 4000, SourceKind.WEB_PAGE: 8000, SourceKind.HISTORY: 600}
MAX_WEB_RESULTS = 5
MAX_WEB_CHARS = 6000              # everything one search contributes to the prompt
MAX_HISTORY = 25

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_STRUCTURE = re.compile(r"</?\s*untrusted\b[^>]*>", re.IGNORECASE)   # the tags the prompt uses for structure


def clean(text: Any) -> str:
    """Text made safe to place in a prompt: no control characters, and none of the prompt's own
    structural tags, which fetched text could otherwise use to step outside its block."""
    return _STRUCTURE.sub("", _CONTROL.sub("", str(text or ""))).strip()


def valid_web_url(url: Any) -> bool:
    try:
        parts = urlsplit(str(url or "").strip())
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname) and "." in parts.hostname


class Passage(BaseModel):
    """One piece of text the model may read, with where it came from."""

    model_config = ConfigDict(frozen=True)

    id: str                                    # short handle within the turn, e.g. "w2"
    kind: SourceKind
    text: str = Field(min_length=1)            # the content itself, already cleaned and capped
    trust: Trust
    title: str = ""
    source_ref: str = ""                       # a URL for web text; a record id for memory
    summary: str = ""                          # the search snippet, when `text` is the page itself
    note: str = ""                             # e.g. why a page could not be read
    owner_id: str | None = None                # whose memory this is
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    truncated: bool = False
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _rules(self) -> Passage:
        if self.kind in UNTRUSTED_KINDS:
            if self.trust is not Trust.UNTRUSTED:
                raise ValueError(f"{self.kind.value} text is third-party text and must be untrusted")
            if not valid_web_url(self.source_ref):
                raise ValueError("web text needs an http(s) address")
        if self.kind in OWNED_KINDS and not self.owner_id:
            raise ValueError(f"{self.kind.value} text needs an owner")
        if self.text != clean(self.text):
            raise ValueError("text must be cleaned before it becomes a passage")
        return self


class Rejected(BaseModel):
    """A candidate that did not become a passage, and why."""

    kind: SourceKind
    reason: str            # empty | bad_url | wrong_owner | low_score | duplicate | over_budget | invalid
    source_ref: str = ""


def _clip(text: str, limit: int) -> tuple[str, bool]:
    return (text, False) if len(text) <= limit else (text[:limit].rstrip(), True)


def _fingerprint(text: str) -> str:
    return hashlib.sha256(" ".join(text.lower().split()).encode()).hexdigest()


class ContextBundle:
    """The validated context for one turn."""

    def __init__(self, user_id: str | None = None) -> None:
        self.user_id = str(user_id) if user_id is not None else None
        self.passages: list[Passage] = []
        self.rejected: list[Rejected] = []
        self._seen_text: set[str] = set()
        self._seen_refs: set[str] = set()
        self._shown_text: list[str] = []       # every tool result the model read, for the link check
        self.reply_check: dict[str, Any] | None = None

    # -- building ---------------------------------------------------------

    def _reject(self, kind: SourceKind, reason: str, source_ref: Any = "") -> None:
        self.rejected.append(Rejected(kind=kind, reason=reason, source_ref=str(source_ref or "")[:300]))

    def _add(self, kind: SourceKind, prefix: str, text: str, *, source_ref: str, dedupe_ref: bool = True,
             **fields: Any) -> Passage | None:
        text, truncated = _clip(clean(text), MAX_PASSAGE_CHARS[kind])
        if not text:
            self._reject(kind, "empty", source_ref)
            return None
        mark = _fingerprint(text)
        if mark in self._seen_text or (dedupe_ref and source_ref and source_ref in self._seen_refs):
            self._reject(kind, "duplicate", source_ref)
            return None
        number = sum(1 for p in self.passages if p.id.startswith(prefix)) + 1
        try:
            passage = Passage(id=f"{prefix}{number}", kind=kind, text=text, source_ref=source_ref, truncated=truncated,
                              trust=Trust.UNTRUSTED if kind in UNTRUSTED_KINDS else Trust.TRUSTED, **fields)
        except ValueError:
            self._reject(kind, "invalid", source_ref)
            return None
        self._seen_text.add(mark)
        if source_ref:
            self._seen_refs.add(source_ref)
        self.passages.append(passage)
        return passage

    def add_web_results(self, items: Any) -> list[Passage]:
        """Search results as the web_search tool returns them: dicts with title, url, snippet and,
        when the page was read, page_text (else page_status)."""
        added: list[Passage] = []
        budget = MAX_WEB_CHARS
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                self._reject(SourceKind.WEB_SEARCH, "invalid")
                continue
            url = str(item.get("url") or "").strip()
            if not valid_web_url(url):
                self._reject(SourceKind.WEB_SEARCH, "bad_url", url)
                continue
            if len(added) >= MAX_WEB_RESULTS or budget <= 0:
                self._reject(SourceKind.WEB_SEARCH, "over_budget", url)
                continue
            snippet, page = clean(item.get("snippet")), clean(item.get("page_text"))
            body, _ = _clip(page or snippet, max(budget, 0))
            passage = self._add(
                SourceKind.WEB_SEARCH, "w", body, source_ref=url, title=clean(item.get("title"))[:300],
                summary=snippet[:500] if page else "", note="" if page else clean(item.get("page_status"))[:200],
            )
            if passage:
                added.append(passage)
                budget -= len(passage.text)
        return added

    def add_web_page(self, url: Any, text: Any, status: Any = "") -> Passage | None:
        """A page fetched by read_webpage."""
        url = str(url or "").strip()
        if not valid_web_url(url):
            self._reject(SourceKind.WEB_PAGE, "bad_url", url)
            return None
        # the same page may be read again later in a turn; a second read is not a duplicate to drop
        return self._add(SourceKind.WEB_PAGE, "p", str(text or ""), source_ref=url, dedupe_ref=False,
                         note=clean(status)[:100])

    def add_history(self, hits: Any, *, min_score: float, exclude_conversation: str | None = None) -> list[dict[str, Any]]:
        """Past messages from a memory search. Returns the hits that passed, unchanged and in order,
        so existing code that renders them keeps working; the passages are on the bundle."""
        kept: list[dict[str, Any]] = []
        for hit in hits if isinstance(hits, list) else []:
            if not isinstance(hit, dict):
                self._reject(SourceKind.HISTORY, "invalid")
                continue
            ref = str(hit.get("id") or "")
            if exclude_conversation and str(hit.get("conversation_id")) == exclude_conversation:
                continue                                    # the current conversation is already in the prompt
            owner = hit.get("user_id")
            if self.user_id is None or owner is None or str(owner) != self.user_id:
                self._reject(SourceKind.HISTORY, "wrong_owner", ref)
                continue
            try:
                score = float(hit.get("score"))
            except (TypeError, ValueError):
                self._reject(SourceKind.HISTORY, "invalid", ref)
                continue
            if score < min_score:
                self._reject(SourceKind.HISTORY, "low_score", ref)
                continue
            if len(kept) >= MAX_HISTORY:
                self._reject(SourceKind.HISTORY, "over_budget", ref)
                continue
            passage = self._add(SourceKind.HISTORY, "h", str(hit.get("content") or ""), source_ref=ref,
                                owner_id=str(owner), score=min(max(score, 0.0), 1.0),
                                title="user" if hit.get("role") == "user" else "assistant")
            if passage:
                kept.append(hit)
        return kept

    def note_shown(self, text: Any) -> None:
        """Remember text the model was shown outside the passages (other tool results), so links
        it repeats from there are not reported as invented."""
        if text:
            self._shown_text.append(str(text))

    # -- rendering --------------------------------------------------------

    def _untrusted_block(self, body: str) -> str:
        return f'<untrusted source="web">\n{body}\n</untrusted>'

    def render_web_results(self, passages: list[Passage], empty: str = "No results found.") -> str:
        """The only way search results reach a prompt."""
        if not passages:
            return self._untrusted_block(empty)
        blocks = []
        for p in passages:
            block = f"• [{p.id}] {p.title}\n  URL: {p.source_ref}"
            if p.summary:
                block += f"\n  Snippet: {p.summary}\n  Page text (read from the site):\n  {p.text}"
            else:
                block += f"\n  Snippet: {p.text}"
                if p.note:
                    block += f"\n  (Page not read: {p.note})"
            if p.truncated:
                block += "\n  [cut short; use read_webpage on this URL for more]"
            blocks.append(block)
        dropped = sum(1 for r in self.rejected if r.kind is SourceKind.WEB_SEARCH and r.reason == "over_budget")
        tail = f"\n\n[{dropped} more results not shown]" if dropped else ""
        return self._untrusted_block("Search results:\n" + "\n\n".join(blocks) + tail)

    def render_web_page(self, passage: Passage | None, failure: str = "The page could not be read.") -> str:
        """The only way a fetched page reaches a prompt."""
        if passage is None:
            return self._untrusted_block(clean(failure))
        tail = "\n[the page is longer than shown]" if passage.truncated else ""
        return self._untrusted_block(f"[{passage.id}] Page fetched: {passage.source_ref}\n\n{passage.text}{tail}")

    # -- reporting --------------------------------------------------------

    def report(self) -> dict[str, Any]:
        """What goes on the turn's trace: every passage's identity (not its full text) and every rejection."""
        reasons: dict[str, int] = {}
        for r in self.rejected:
            reasons[r.reason] = reasons.get(r.reason, 0) + 1
        return {
            "passages": [{"id": p.id, "kind": p.kind.value, "trust": p.trust.value, "source_ref": p.source_ref[:300],
                          "title": p.title[:120], "chars": len(p.text), "score": p.score, "truncated": p.truncated}
                         for p in self.passages],
            "rejected": [r.model_dump(mode="json") for r in self.rejected[:50]],
            "rejected_by_reason": reasons,
            "reply_check": self.reply_check,
        }

    def all_shown_text(self) -> str:
        parts = [f"{p.source_ref}\n{p.title}\n{p.summary}\n{p.text}" for p in self.passages]
        return "\n".join(parts + self._shown_text)


# ---------------------------------------------------------------------------
# Grounding: is this quote really in that source?
# ---------------------------------------------------------------------------
#
# The rules above cover text that comes straight from a source. A second kind of context is
# written by a model: a research "finding", a summary of a page. It is handed to the next
# model call as if it were fact, so before it goes it must be tied back to the source text
# it claims to come from. That link is a quote, and a quote can be checked by code.

_QUOTE_MARKS = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2032": "'", "\u2033": '"',
                              "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2212": "-",
                              "\u00a0": " ", "\u202f": " ", "\u2009": " ", "\u200b": "", "\u00ad": ""})
_ELLIPSIS = re.compile(r"\s*(?:\.\.\.|\u2026|\[\.\.\.\]|\[\u2026\])\s*")
MIN_QUOTE_CHARS = 12          # shorter than this, "a quote" could match almost any text
MIN_QUOTE_WORDS = 3


def normalise_for_match(text: Any) -> str:
    """Text reduced to what must match: Unicode forms unified, typographic quotes and dashes made
    plain, whitespace collapsed, case folded. Nothing else is forgiven: a changed word or number
    does not match."""
    import unicodedata

    plain = unicodedata.normalize("NFKC", str(text or "")).translate(_QUOTE_MARKS)
    return " ".join(plain.casefold().split())


class QuoteCheck(BaseModel):
    """The result of looking for a quote in a source."""

    found: bool
    reason: str = ""                 # "" | too_short | not_in_source | out_of_order
    segments: int = 0                # parts the quote was split into at ellipses
    start: int | None = None         # where it starts in the normalised source, when found


def find_quote(quote: Any, source_text: Any) -> QuoteCheck:
    """Whether `quote` appears in `source_text`, word for word.

    A quote may leave words out with an ellipsis; each part must then appear, in order. Apart from
    that and the normalisation above the match is exact, on purpose: a paraphrase is the model's
    wording, and the point of the check is to tell the source's words from the model's.
    """
    source = normalise_for_match(source_text)
    whole = normalise_for_match(str(quote or "").strip().strip('"\u201c\u201d'))
    if len(whole) < MIN_QUOTE_CHARS or len(whole.split()) < MIN_QUOTE_WORDS:
        return QuoteCheck(found=False, reason="too_short")
    parts = [p.strip(" .") for p in _ELLIPSIS.split(whole)]
    parts = [p for p in parts if p]
    if not parts:
        return QuoteCheck(found=False, reason="too_short")
    position, first = 0, None
    for part in parts:
        at = source.find(part, position)
        if at == -1:
            elsewhere = source.find(part) != -1
            return QuoteCheck(found=False, reason="out_of_order" if elsewhere else "not_in_source", segments=len(parts))
        first = at if first is None else first
        position = at + len(part)
    return QuoteCheck(found=True, segments=len(parts), start=first)


def quoted_spans(text: str, min_chars: int = 25) -> list[str]:
    """Passages a reply presents as someone's exact words: text inside double quotation marks and
    Markdown block quotes. Short quoted words (titles, names, scare quotes) are left out."""
    pattern = '["\u201c]([^"\u201c\u201d\\n]{' + str(min_chars) + ',})["\u201d]'
    spans = [m.group(1).strip() for m in re.finditer(pattern, text or "")]
    block: list[str] = []
    for line in (text or "").splitlines() + [""]:
        if line.lstrip().startswith(">"):
            block.append(line.lstrip()[1:].strip())
        elif block:
            joined = " ".join(b for b in block if b)
            if len(joined) >= min_chars:
                spans.append(joined)
            block = []
    seen: dict[str, None] = {}
    for span in spans:
        seen.setdefault(span, None)
    return list(seen)


def bundle_for(state: Any) -> ContextBundle:
    """The one bundle for a turn, kept on the workflow state so both chat engines share it."""
    bundle = getattr(state, "context_bundle", None)
    if bundle is None:
        bundle = ContextBundle(getattr(getattr(state, "user", None), "id", None))
        state.context_bundle = bundle
    return bundle


# ---------------------------------------------------------------------------
# After the reply
# ---------------------------------------------------------------------------

_URL = re.compile(r"https?://[^\s<>\"'`\]\[]+", re.IGNORECASE)
_TRAILING = ").,;:!?*_>}"
# Links the app builds itself as "search for this" suggestions: navigation, not a cited source.
_SEARCH_LINK = re.compile(r"^https?://(www\.)?(google|bing|duckduckgo)\.[a-z.]+/(search|\?q=)", re.IGNORECASE)


def _normalise_url(url: str) -> str:
    url = url.strip()
    while url and url[-1] in _TRAILING:
        if url[-1] == ")" and url.count("(") >= url.count(")"):
            break                                            # a bracket that belongs to the address
        url = url[:-1]
    return url.split("#", 1)[0].rstrip("/").lower()


def links_in(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for match in _URL.findall(text or ""):
        url = _normalise_url(match)
        if url:
            seen.setdefault(url, None)
    return list(seen)


def check_reply(reply: str, bundle: ContextBundle, also_allowed: str = "") -> dict[str, Any]:
    """Links and quotations in the reply that appear nowhere in what the model was shown or what
    the user said.

    A link like that came from the model's own memory. It may be right, but nothing in this turn
    supports it, so it is reported (on the trace, and in the log) for a person or an eval to
    look at. Search-engine links the app suggests on purpose are not counted.
    """
    shown = bundle.all_shown_text() + "\n" + (also_allowed or "")
    known = {_normalise_url(u) for u in links_in(shown)}
    given = links_in(reply)
    unsourced = [u for u in given if u not in known and not _SEARCH_LINK.match(u)]
    # Anything the reply presents as an exact quotation must be word for word in what was shown.
    quotes = quoted_spans(reply)
    unsupported = [q[:200] for q in quotes if not find_quote(q, shown).found]
    return {"links": len(given), "unsourced_links": unsourced[:20],
            "quotes": len(quotes), "unsupported_quotes": unsupported[:20]}
