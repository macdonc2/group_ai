"""Synthesis across lanes and the alphaxiv-style write-up."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

from agent_system.adapters.outbound.llm.personas import report_persona_suffix
from agent_system.adapters.outbound.research.llm import make_agent
from agent_system.adapters.outbound.research.schemas import Synthesis
from agent_system.domain.entities.research import DataTable, Figure, Lane, LaneResult, Source

FIGURE_TOKEN = "![Figure {n}](figure:{n})"
_FIG_RE = re.compile(r"!\[[^\]]*\]\(figure:(\d+)\)")

SECTION_ORDER = [
    "Background and Motivation",
    "What the Research Says",
    "How It Is Done in Practice",
    "What the Numbers Show",
    "Synthesis: Where the Lanes Agree and Disagree",
    "Open Questions",
]


def number_sources(results: dict[Lane, LaneResult]) -> tuple[list[Source], dict[str, int]]:
    """Cited sources get reference numbers in lane order; uncited ones are dropped."""
    cited: set[str] = set()
    for r in results.values():
        cited |= {f.source_id for f in r.findings}
        for t in r.tables:
            cited |= set(t.source_ids)
    ordered: list[Source] = []
    for lane in ("academic", "practical", "empirical"):
        for s in results[lane].sources:
            if s.id in cited:
                ordered.append(s)
    ref_by_source = {}
    numbered = []
    for i, s in enumerate(ordered, 1):
        ref_by_source[s.id] = i
        numbered.append(s.model_copy(update={"ref": i}))
    return numbered, ref_by_source


def _findings_block(results: dict[Lane, LaneResult], ref_by_source: dict[str, int]) -> str:
    out = []
    for lane in ("academic", "practical", "empirical"):
        r = results[lane]
        out.append(f"### {lane.upper()} LANE" + (f" (error: {r.error})" if r.error else ""))
        for i, summary in enumerate(r.summaries, 2):
            out.append(f"(round {i} review) {summary}")
        for f in r.findings:
            ref = ref_by_source.get(f.source_id)
            out.append(f"- [{ref}] {f.claim}\n  evidence: {f.evidence}")
    return "\n".join(out)


def _tables_block(tables: list[DataTable]) -> str:
    out = []
    for i, t in enumerate(tables, 1):
        series = "; ".join(
            f"{s.name}: " + ", ".join(f"{p.x}={p.y:g}" for p in s.points) for s in t.series
        )
        out.append(f"T{i}. {t.title} [{t.unit or 'no unit'}] — {series} (sources {', '.join(t.source_ids)})")
    return "\n".join(out) or "(none)"


async def synthesize(
    question: str,
    results: dict[Lane, LaneResult],
    tables: list[DataTable],
    ref_by_source: dict[str, int],
    model: str,
    api_key: str,
) -> Synthesis:
    agent = make_agent(
        model, api_key,
        system_prompt=(
            "You are the editor integrating three research lanes (academic literature, "
            "practitioner/software experience, empirical numbers) into one coherent story. "
            "Be concrete. Note where lanes agree, where they conflict, and what nobody has "
            "answered. Plan sections in this order and with these exact headings: "
            + "; ".join(SECTION_ORDER)
            + ". Choose which extracted tables deserve a chart (ordinals from the T-list), "
            "best first, at most 4, only tables with real comparative signal."
        ),
        output_type=Synthesis,
    )
    prompt = (
        f"Research question: {question}\n\n"
        f"Findings by lane (numbers in brackets are citation refs):\n{_findings_block(results, ref_by_source)}\n\n"
        f"Extracted data tables:\n{_tables_block(tables)}"
    )
    result = await agent.run(prompt)
    syn = result.output
    syn.figures_to_use = [n for n in syn.figures_to_use if 1 <= n <= len(tables)][:4]
    if not syn.figures_to_use and tables:
        # The editor declined to pick; a report with real numbers and no chart
        # is worse than one with a modest chart. Take the tables that can carry one.
        syn.figures_to_use = [
            i for i, t in enumerate(tables, 1)
            if sum(len(s.points) for s in t.series) >= 2
        ][:2]
    return syn


def source_figure_caption(ordinal: int, paper_caption: str, source: Source, ref: int | None, fig_number: int | None) -> str:
    """Caption for a figure lifted from a paper, ending with a link to that paper."""
    own = f" (their Figure {fig_number})" if fig_number else ""
    text = paper_caption.strip()
    if len(text) > 260:
        text = text[:257].rstrip() + "…"
    body = f"{text}{own}" if text else f"Figure from {source.title}{own}"
    cite = f" [{ref}]" if ref else ""
    link = f" — [{source.title}]({source.url})" if source.url else f" — {source.title}"
    return f"Figure {ordinal}: {body}{cite}{link}"


def _references_block(sources: list[Source]) -> str:
    lines = ["## References", ""]
    for s in sources:
        who = ", ".join(s.authors[:3]) + (" et al." if len(s.authors) > 3 else "")
        meta = " · ".join(x for x in [who or None, str(s.year) if s.year else None, s.venue] if x)
        link = f" — {s.url}" if s.url else ""
        lines.append(f"{s.ref}. **{s.title}**" + (f" ({meta})" if meta else "") + link)
    return "\n".join(lines)


async def write_report(
    question: str,
    synthesis: Synthesis,
    results: dict[Lane, LaneResult],
    figures: list[Figure],
    sources: list[Source],
    ref_by_source: dict[str, int],
    model: str,
    api_key: str,
    persona: str | None = None,
) -> AsyncIterator[str]:
    """Stream the markdown body. The caller appends references and fixes figures."""
    fig_lines = "\n".join(
        f"Figure {f.ordinal} ({'from the paper' if f.origin == 'source' else 'chart from extracted data'}): {f.caption} — "
        f"place with the token {FIGURE_TOKEN.format(n=f.ordinal)} on its own line"
        for f in figures
    ) or "(no figures)"
    plan = "\n".join(
        f"## {s.heading}\n" + "\n".join(f"- {p}" for p in s.key_points)
        + (f"\n  cite: {', '.join(str(ref_by_source.get(i, '?')) for i in s.source_ids)}" if s.source_ids else "")
        + (f"\n  figures: {s.figure_ordinals}" if s.figure_ordinals else "")
        for s in synthesis.sections
    )
    agent = make_agent(
        model, api_key,
        system_prompt=(
            "You write research overviews in the alphaXiv house style: an explanatory, "
            "accessible academic register for a technically literate reader who is new to "
            "the specific topic. Paragraphs of 4-6 sentences. Precise but never padded. "
            "Use markdown: `# Title`, a `**TL;DR**` paragraph, then `##` sections with the "
            "headings given, in order. Cite with bracketed numbers like [3] immediately after "
            "the claim they support; never invent a citation and never cite a number that "
            "is not in the list. Place each figure token exactly once, on its own line, in "
            "the section it belongs to, and refer to it in the prose ('Figure 2 shows…'). "
            "Do not write a References section; it is appended for you. "
            "Do not use tables. Equations are fine in LaTeX ($…$) when they clarify."
        ) + report_persona_suffix(persona),
    )
    prompt = (
        f"Research question: {question}\n\nTitle: {synthesis.title}\nTL;DR: {synthesis.tldr}\n\n"
        f"Section plan:\n{plan}\n\nAgreements: {synthesis.agreements}\nDisagreements: {synthesis.disagreements}\n"
        f"Open questions: {synthesis.open_questions}\n\nFigures:\n{fig_lines}\n\n"
        f"Evidence (for accurate citation):\n{_findings_block(results, ref_by_source)}\n\n"
        f"Numbered sources:\n" + "\n".join(f"[{s.ref}] {s.title}" for s in sources)
        + "\n\nWrite the full overview now, 1100-1700 words."
    )
    async with agent.run_stream(prompt) as stream:
        async for delta in stream.stream_text(delta=True):
            yield delta


def finalize_markdown(body: str, figures: list[Figure], sources: list[Source]) -> str:
    """Guarantee every figure appears exactly once, then append references."""
    seen = set()

    def _dedupe(m: re.Match) -> str:
        n = int(m.group(1))
        if n in seen:
            return ""
        seen.add(n)
        return FIGURE_TOKEN.format(n=n)

    body = _FIG_RE.sub(_dedupe, body)
    missing = [f for f in figures if f.ordinal not in seen]
    if missing:
        block = "\n\n".join(f"{FIGURE_TOKEN.format(n=f.ordinal)}\n*{f.caption}*" for f in missing)
        marker = "## Synthesis"
        if marker in body:
            body = body.replace(marker, block + "\n\n" + marker, 1)
        else:
            body = body.rstrip() + "\n\n" + block
    return body.rstrip() + "\n\n" + _references_block(sources) + "\n"


def narration_script(markdown: str, figures: list[Figure]) -> str:
    """Plain spoken text: no markdown, captions read aloud, references skipped."""
    text = markdown.split("\n## References")[0]
    captions = {f.ordinal: f.caption for f in figures}
    text = _FIG_RE.sub(lambda m: captions.get(int(m.group(1)), "").replace("Figure", "Figure", 1), text)
    text = re.sub(r"^#+\s*", "", text, flags=re.M)              # headings
    text = re.sub(r"\*\*TL;DR\*\*", "Too long, didn't read.", text)
    text = re.sub(r"[*_`>#]", "", text)                           # emphasis, code, quotes
    text = re.sub(r"\[(\d+)\]", "", text)                         # citations
    text = re.sub(r"\$[^$]+\$", "", text)                         # inline math
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)          # links
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
