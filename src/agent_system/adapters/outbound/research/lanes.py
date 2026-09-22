"""The three research lanes.

Each lane has the same shape: plan queries → gather sources → ask the model
for findings (and, for the empirical lane, data tables). Lanes emit progress
through `emit(event_type, lane, message, data)` and never raise; a failure
becomes `LaneResult.error` so the other lanes and the synthesis still run.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from agent_system.adapters.outbound.research import sources as src
from agent_system.adapters.outbound.research.llm import make_agent
from agent_system.adapters.outbound.research.schemas import FindingsOut, GapPlan, QueryPlan, TablesOut
from agent_system.domain.entities.research import DataTable, Finding, Lane, LaneResult, Source

logger = logging.getLogger(__name__)

Emit = Callable[[str, str, str, dict | None], Awaitable[None]]


@dataclass
class LaneDeps:
    api_key: str
    strong_model: str   # gpt-6-astra: planning, findings, extraction of numbers
    fast_model: str     # gpt-5.6-luna: ranking / light structured work
    semantic_scholar_key: str | None = None
    github_token: str | None = None
    max_sources: int = 10
    max_pages: int = 6
    depth: int = 1      # rounds per lane; rounds >1 re-plan from the gaps in what's known


def _sources_block(sources: list[Source], with_snippets: bool = True) -> str:
    lines = []
    for s in sources:
        meta = " · ".join(x for x in [", ".join(s.authors[:3]) or None, str(s.year) if s.year else None, s.venue] if x)
        lines.append(f"[{s.id}] {s.title}" + (f" ({meta})" if meta else "") + (f"\n    {s.url}" if s.url else ""))
        if with_snippets and s.snippet:
            lines.append(f"    {s.snippet}")
    return "\n".join(lines)


async def _plan_queries(question: str, lane: Lane, deps: LaneDeps, n: int) -> list[str]:
    guidance = {
        "academic": (
            "Queries for arXiv and Semantic Scholar. Use the field's own terminology, "
            "name the core methods, include one query for surveys/reviews and one for "
            "the most recent work. No years, no quotes, no boolean operators."
        ),
        "practical": (
            "Queries for the open web and GitHub aimed at practitioners: libraries, "
            "frameworks, implementation guides, engineering blog posts, tutorials, "
            "known pitfalls, production experience. One query should be GitHub-shaped "
            "(a library or tool name plus what it does)."
        ),
        "empirical": (
            "Queries that surface NUMBERS: benchmarks, leaderboards, reported results, "
            "ablations, comparisons, error rates, speedups, costs. Use words like "
            "benchmark, results, comparison, evaluation, performance."
        ),
    }[lane]
    agent = make_agent(
        deps.fast_model, deps.api_key,
        system_prompt=(
            "You plan search queries for a research assistant. Return a short list of "
            f"distinct, specific queries. {guidance}"
        ),
        output_type=QueryPlan,
    )
    result = await agent.run(f"Research question: {question}\n\nReturn {n} queries.")
    return [q.strip() for q in result.output.queries if q.strip()][:n]


async def _gap_plan(question: str, lane: Lane, findings: list[Finding], deps: LaneDeps, n: int) -> GapPlan:
    """Recursive step: condense what this lane knows, name the gaps, plan queries for them."""
    agent = make_agent(
        deps.strong_model, deps.api_key,
        system_prompt=(
            f"You are reviewing what the {lane} research lane has established so far. "
            "Write a tight summary of the findings (5-8 sentences), then list the most "
            "important GAPS: sub-questions the question needs answered that the findings "
            "don't cover, conflicts that need a tie-breaker, and claims that rest on one "
            f"source. Then plan {n} NEW search queries aimed squarely at those gaps, "
            "phrased for the same sources this lane uses. Never repeat ground already covered."
        ),
        output_type=GapPlan,
    )
    block = "\n".join(f"- ({f.source_id}) {f.claim}" for f in findings) or "(no findings yet)"
    result = await agent.run(f"Research question: {question}\n\nFindings so far:\n{block}")
    plan = result.output
    plan.queries = [q.strip() for q in plan.queries if q.strip()][:n]
    return plan


async def _search(lane: Lane, queries: list[str], deps: LaneDeps) -> list[Source]:
    if lane == "academic":
        batches = await src.gather_soft(
            *(src.search_arxiv(q, 8) for q in queries),
            src.search_semantic_scholar_many(queries, 8, deps.semantic_scholar_key),
        )
    elif lane == "practical":
        batches = await src.gather_soft(
            *(src.search_web(q, 6) for q in queries),
            *(src.search_github(q, 4, deps.github_token) for q in queries[:2]),
        )
    else:
        batches = await src.gather_soft(*(src.search_web(q, 6) for q in queries))
    return src.dedupe([s for b in batches for s in b])


async def _findings(question: str, lane: Lane, sources: list[Source], deps: LaneDeps) -> FindingsOut:
    role = {
        "academic": "an academic literature reviewer: precise about methods, datasets and what was actually shown",
        "practical": "a senior engineer surveying how this is done in practice: tools, libraries, patterns, trade-offs, maturity, gotchas",
        "empirical": "a meticulous analyst who only reports quantitative results and their conditions",
    }[lane]
    agent = make_agent(
        deps.strong_model, deps.api_key,
        system_prompt=(
            f"You are {role}. From the sources provided, extract findings that bear on the "
            "research question. A finding is one claim, supported by a quoted or closely "
            "paraphrased span from ONE source (cite its id). Prefer specific over general. "
            "Skip sources that are off-topic and list them as dropped. 6-12 findings."
        ),
        output_type=FindingsOut,
    )
    prompt = f"Research question: {question}\n\nSources:\n{_sources_block(sources)}"
    result = await agent.run(prompt)
    valid = {s.id for s in sources}
    findings = [f for f in result.output.findings if f.source_id in valid]
    return FindingsOut(findings=findings, dropped_source_ids=result.output.dropped_source_ids)


async def _tables(question: str, sources: list[Source], deps: LaneDeps) -> list[DataTable]:
    agent = make_agent(
        deps.strong_model, deps.api_key,
        system_prompt=(
            "You extract quantitative results into small data tables for charting. Rules: "
            "only numbers that appear in the source text (copy the span into `quote`); "
            "one table per comparable set (same metric, same unit); 2-8 points per series; "
            "x values are category labels (model names, methods, years) or numbers; give "
            "a clear title, axis labels and unit; cite the source ids. If a source has no "
            "usable numbers, skip it. Return at most 6 tables, best first."
        ),
        output_type=TablesOut,
    )
    prompt = f"Research question: {question}\n\nSources:\n{_sources_block(sources)}"
    result = await agent.run(prompt)
    valid = {s.id for s in sources}
    tables = []
    for t in result.output.tables:
        if not t.series or not any(s.points for s in t.series):
            continue
        t.source_ids = [i for i in t.source_ids if i in valid]
        tables.append(t)
    return tables[:6]


async def _enrich_with_pages(sources: list[Source], limit: int) -> list[Source]:
    """Replace snippets with page text for the first `limit` web sources."""
    targets = [s for s in sources if s.url and s.venue != "GitHub"][:limit]
    texts = await src.gather_soft(*(src.fetch_readable(s.url or "") for s in targets))
    by_id = {s.id: t for s, t in zip(targets, texts)}
    out = []
    for s in sources:
        text = by_id.get(s.id)
        out.append(s.model_copy(update={"snippet": text[:src.PAGE_CHARS]}) if text else s)
    return out


async def run_lane(lane: Lane, question: str, deps: LaneDeps, emit: Emit) -> LaneResult:
    from agent_system.adapters.outbound.telemetry import set_current_node

    set_current_node(f"lane:{lane}")  # gather() gives each lane its own context
    result = LaneResult(lane=lane)
    try:
        await emit("lane_start", lane, f"{lane.title()} lane starting", None)

        # 1. queries
        await emit("lane_step", lane, "Planning queries", {"step": "queries"})
        queries = await _plan_queries(question, lane, deps, n=4 if lane != "empirical" else 3)
        result.queries = queries
        await emit("lane_queries", lane, f"{len(queries)} queries planned", {"queries": queries})

        # 2. sources
        await emit("lane_step", lane, "Searching sources", {"step": "search"})
        found = await _search(lane, queries, deps)
        found = [s for s in found if s.snippet or s.venue == "GitHub"][: deps.max_sources * 2]
        sources = src.assign_ids(found[: deps.max_sources], lane)
        if lane in ("practical", "empirical"):
            await emit("lane_step", lane, "Reading pages", {"step": "fetch"})
            sources = await _enrich_with_pages(sources, deps.max_pages)
        result.sources = sources
        await emit(
            "lane_sources", lane, f"{len(sources)} sources gathered",
            {"sources": [s.model_dump(exclude={"snippet"}) for s in sources]},
        )
        if not sources:
            result.error = "No sources found"
            await emit("lane_complete", lane, "No sources found", {"findings": 0, "sources": 0})
            return result

        # 3. findings / tables
        await emit("lane_step", lane, "Extracting findings", {"step": "findings"})
        fo = await _findings(question, lane, sources, deps)
        result.findings = fo.findings
        for f in fo.findings:
            await emit("lane_finding", lane, f.claim, {"source_id": f.source_id, "confidence": f.confidence})

        # 4. deeper rounds: summarise -> gaps -> new queries -> new sources -> new findings
        for rnd in range(2, max(1, deps.depth) + 1):
            await emit("lane_round", lane, f"Round {rnd}: reviewing what's known and where the gaps are", {"round": rnd})
            plan = await _gap_plan(question, lane, result.findings, deps, n=3)
            result.summaries.append(plan.summary)
            await emit("lane_gaps", lane, plan.summary, {"round": rnd, "gaps": plan.gaps, "summary": plan.summary})
            if not plan.queries:
                break
            await emit("lane_queries", lane, f"Round {rnd}: {len(plan.queries)} gap-driven queries", {"queries": plan.queries, "round": rnd})
            result.queries.extend(plan.queries)
            seen = {(s.url or "").rstrip("/").lower() for s in result.sources} | {s.title.lower() for s in result.sources}
            fresh = [s for s in await _search(lane, plan.queries, deps)
                     if (s.url or "").rstrip("/").lower() not in seen and s.title.lower() not in seen]
            fresh = [s for s in fresh if s.snippet or s.venue == "GitHub"][: deps.max_sources]
            # ids continue after the existing ones so citations stay unique
            prefix = {"academic": "A", "practical": "P", "empirical": "E"}[lane]
            fresh = [s.model_copy(update={"id": f"{prefix}{len(result.sources) + i}", "lane": lane}) for i, s in enumerate(fresh, 1)]
            if lane in ("practical", "empirical") and fresh:
                await emit("lane_step", lane, f"Round {rnd}: reading pages", {"step": "fetch", "round": rnd})
                fresh = await _enrich_with_pages(fresh, deps.max_pages)
            await emit("lane_sources", lane, f"Round {rnd}: {len(fresh)} new sources",
                       {"sources": [s.model_dump(exclude={"snippet"}) for s in fresh], "round": rnd})
            if not fresh:
                continue
            result.sources.extend(fresh)
            await emit("lane_step", lane, f"Round {rnd}: extracting findings", {"step": "findings", "round": rnd})
            more = await _findings(question, lane, fresh, deps)
            result.findings.extend(more.findings)
            for f in more.findings:
                await emit("lane_finding", lane, f.claim, {"source_id": f.source_id, "confidence": f.confidence, "round": rnd})

        if lane == "empirical":
            await emit("lane_step", lane, "Extracting numbers", {"step": "tables"})
            result.tables = await _tables(question, result.sources, deps)
            await emit("lane_tables", lane, f"{len(result.tables)} data tables extracted",
                       {"tables": [t.model_dump() for t in result.tables]})

        await emit(
            "lane_complete", lane,
            f"{lane.title()} lane done: {len(result.findings)} findings from {len(result.sources)} sources"
            + (f" over {deps.depth} rounds" if deps.depth > 1 else ""),
            {"findings": len(result.findings), "sources": len(result.sources), "tables": len(result.tables), "rounds": deps.depth},
        )
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("%s lane failed", lane)
        result.error = str(exc)[:300]
        await emit("lane_error", lane, f"{lane.title()} lane failed: {result.error}", {"error": result.error})
        return result


async def run_all_lanes(question: str, deps: LaneDeps, emit: Emit) -> dict[Lane, LaneResult]:
    results = await asyncio.gather(
        run_lane("academic", question, deps, emit),
        run_lane("practical", question, deps, emit),
        run_lane("empirical", question, deps, emit),
    )
    return {r.lane: r for r in results}


async def empirical_from_academic(question: str, academic: LaneResult, deps: LaneDeps) -> list[DataTable]:
    """Second pass: abstracts often carry the headline numbers too."""
    if not academic.sources:
        return []
    try:
        return await _tables(question, academic.sources, deps)
    except Exception as exc:  # noqa: BLE001
        logger.warning("empirical pass over academic sources failed: %s", exc)
        return []
