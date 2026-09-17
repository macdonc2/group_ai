"""In-process runner for Deep Research jobs.

One asyncio task per job. Every progress event is persisted on the job row
(except the high-volume writing deltas) so a client can replay history, and
fanned out to live subscribers so it can tail the rest. Nothing here survives
a process restart; `mark_interrupted_on_startup` says so on the rows.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from agent_system.adapters.outbound.persistence.database import Database
from agent_system.adapters.outbound.persistence.research_repositories import (
    SQLAlchemyResearchRepository,
)
from agent_system.adapters.outbound.research import figures as figs
from agent_system.adapters.outbound.research import narration
from agent_system.adapters.outbound.research import source_figures
from agent_system.adapters.outbound.research import writer
from agent_system.adapters.outbound.research.lanes import LaneDeps, empirical_from_academic, run_all_lanes
from agent_system.domain.entities.research import (
    DataTable,
    Figure,
    LaneProgress,
    ResearchProgress,
    ResearchStatus,
)

logger = logging.getLogger(__name__)

TERMINAL_EVENTS = {"job_complete", "job_failed", "job_interrupted"}
UNPERSISTED_EVENTS = {"writing_chunk"}


@dataclass
class ResearchSettings:
    strong_model: str
    fast_model: str
    tts_model: str
    tts_voice: str
    semantic_scholar_key: str | None = None
    github_token: str | None = None


@dataclass
class _LiveJob:
    task: asyncio.Task | None = None
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    seq: int = 0
    done: bool = False


class ResearchRunner:
    def __init__(self, database: Database, settings: ResearchSettings) -> None:
        self._db = database
        self._settings = settings
        self._jobs: dict[str, _LiveJob] = {}

    # ---- subscriptions ----------------------------------------------------

    def subscribe(self, job_id: str) -> asyncio.Queue | None:
        """A queue of live events, or None if the job isn't running here."""
        live = self._jobs.get(job_id)
        if not live or live.done:
            return None
        q: asyncio.Queue = asyncio.Queue()
        live.subscribers.append(q)
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue) -> None:
        live = self._jobs.get(job_id)
        if live and q in live.subscribers:
            live.subscribers.remove(q)

    def is_live(self, job_id: str) -> bool:
        live = self._jobs.get(job_id)
        return bool(live and not live.done)

    # ---- lifecycle --------------------------------------------------------

    def start(self, job_id: str, api_key: str) -> None:
        live = _LiveJob()
        self._jobs[job_id] = live
        live.task = asyncio.create_task(self._run(job_id, api_key, live), name=f"research-{job_id}")

    async def cancel(self, job_id: str) -> bool:
        live = self._jobs.get(job_id)
        if not live or not live.task or live.done:
            return False
        live.task.cancel()
        return True

    async def _emit(self, job_id: str, live: _LiveJob, event_type: str, node: str | None,
                    message: str, data: dict[str, Any] | None) -> None:
        live.seq += 1
        event = {
            "event_type": event_type,
            "node_name": node,
            "message": message,
            "data": {**(data or {}), "seq": live.seq},
            "timestamp": time.time(),
        }
        if event_type not in UNPERSISTED_EVENTS:
            async with self._db.session() as session:
                await SQLAlchemyResearchRepository(session).append_event(job_id, event)
                await session.commit()
        for q in list(live.subscribers):
            q.put_nowait(event)
        if event_type in TERMINAL_EVENTS:
            live.done = True
            for q in list(live.subscribers):
                q.put_nowait(None)

    async def _update(self, job_id: str, **fields: Any) -> None:
        async with self._db.session() as session:
            await SQLAlchemyResearchRepository(session).update_fields(job_id, **fields)
            await session.commit()

    # ---- the pipeline -----------------------------------------------------

    async def _run(self, job_id: str, api_key: str, live: _LiveJob) -> None:
        s = self._settings
        progress = ResearchProgress(phase="running")

        async def emit(event_type: str, node: str, message: str, data: dict | None) -> None:
            # Keep the progress summary current for late joiners.
            if node in progress.lanes:
                lp: LaneProgress = progress.lanes[node]
                if event_type == "lane_start":
                    lp.status = "running"
                elif event_type == "lane_step":
                    lp.step = message
                elif event_type == "lane_round":
                    lp.round = int((data or {}).get("round", lp.round))
                elif event_type == "lane_queries":
                    lp.queries += len((data or {}).get("queries", []))
                elif event_type == "lane_sources":
                    lp.sources += len((data or {}).get("sources", []))
                elif event_type == "lane_finding":
                    lp.findings += 1
                elif event_type == "lane_tables":
                    lp.tables = len((data or {}).get("tables", []))
                elif event_type == "lane_complete":
                    lp.status = "complete"
                    lp.step = "done"
                elif event_type == "lane_error":
                    lp.status = "error"
                    lp.error = (data or {}).get("error")
                await self._update(job_id, progress=progress)
            await self._emit(job_id, live, event_type, node, message, data)

        try:
            async with self._db.session() as session:
                job = await SQLAlchemyResearchRepository(session).get(job_id)
            if not job:
                return
            question = job.question
            depth = max(1, min(3, int(job.progress.depth or 1)))
            progress.depth = depth
            persona = job.progress.persona
            progress.persona = persona
            for lp in progress.lanes.values():
                lp.round = 1

            await self._update(job_id, status=ResearchStatus.RUNNING, progress=progress)
            await self._emit(job_id, live, "job_start", None, "Research started",
                             {"question": question, "model": s.strong_model, "depth": depth, "persona": persona})

            deps = LaneDeps(
                api_key=api_key, strong_model=s.strong_model, fast_model=s.fast_model,
                semantic_scholar_key=s.semantic_scholar_key, github_token=s.github_token,
                depth=depth,
            )

            # 1. three lanes in parallel
            results = await run_all_lanes(question, deps, emit)

            # 1b. numbers hiding in the academic abstracts
            extra = await empirical_from_academic(question, results["academic"], deps)
            tables: list[DataTable] = results["empirical"].tables + extra
            if extra:
                results["empirical"].tables = tables
                progress.lanes["empirical"].tables = len(tables)

            if not any(r.findings for r in results.values()):
                raise RuntimeError("All three lanes came back empty; nothing to synthesise.")

            # 2. synthesis
            progress.phase = "synthesizing"
            await self._update(job_id, status=ResearchStatus.SYNTHESIZING, progress=progress)
            await self._emit(job_id, live, "synthesis_start", "synthesis", "Integrating the three lanes", None)
            sources, ref_by_source = writer.number_sources(results)
            synthesis = await writer.synthesize(question, results, tables, ref_by_source, s.strong_model, api_key)
            await self._update(job_id, title=synthesis.title, tldr=synthesis.tldr, sources=sources)
            await self._emit(
                job_id, live, "synthesis_complete", "synthesis", synthesis.title,
                {"title": synthesis.title, "tldr": synthesis.tldr, "sections": [sec.heading for sec in synthesis.sections],
                 "agreements": synthesis.agreements, "disagreements": synthesis.disagreements,
                 "sources": [src.model_dump(exclude={"snippet"}) for src in sources]},
            )

            # 3a. figures lifted straight from the most-cited papers (link in caption)
            figures: list[Figure] = []
            await self._emit(job_id, live, "figures_start", "figures", "Looking for figures in the cited papers", None)
            try:
                all_findings = [f for r in results.values() for f in r.findings]
                lifted = await source_figures.figures_from_sources(sources, all_findings, max_total=2)
            except Exception as exc:  # noqa: BLE001
                logger.warning("source figure extraction failed: %s", exc)
                lifted = []
            for ex in lifted:
                png = source_figures.normalise_png(ex.png)
                if not source_figures.png_bytes_ok(png):
                    continue
                ordinal = len(figures) + 1
                fig = Figure(
                    ordinal=ordinal,
                    caption=writer.source_figure_caption(ordinal, ex.caption, ex.source, ref_by_source.get(ex.source.id), ex.number),
                    chart_spec={"page": ex.page, "paper_figure": ex.number, "width": ex.width, "height": ex.height},
                    source_ids=[ex.source.id], origin="source", source_url=ex.source.url, source_title=ex.source.title,
                )
                async with self._db.session() as session:
                    await SQLAlchemyResearchRepository(session).add_figure(job_id, fig, png)
                    await session.commit()
                figures.append(fig)
                progress.figures = len(figures)
                await self._update(job_id, progress=progress)
                await self._emit(job_id, live, "figure_rendered", "figures", fig.caption,
                                 {"ordinal": fig.ordinal, "caption": fig.caption, "origin": "source",
                                  "source_url": fig.source_url, "source_title": fig.source_title})

            # 3b. charts drawn from the extracted numbers
            for t_idx in synthesis.figures_to_use:
                table = tables[t_idx - 1]
                try:
                    png = figs.render_png(table)
                except Exception as exc:  # noqa: BLE001
                    await self._emit(job_id, live, "figure_skipped", "figures",
                                     f"Could not chart '{table.title}': {exc}", None)
                    continue
                fig = Figure(ordinal=len(figures) + 1, caption=figs.caption_for(len(figures) + 1, table, ref_by_source),
                             chart_spec=table.model_dump(), source_ids=table.source_ids)
                async with self._db.session() as session:
                    await SQLAlchemyResearchRepository(session).add_figure(job_id, fig, png)
                    await session.commit()
                figures.append(fig)
                progress.figures = len(figures)
                await self._update(job_id, progress=progress)
                await self._emit(job_id, live, "figure_rendered", "figures", fig.caption,
                                 {"ordinal": fig.ordinal, "caption": fig.caption})

            # 4. write
            progress.phase = "writing"
            await self._update(job_id, status=ResearchStatus.WRITING, progress=progress)
            await self._emit(job_id, live, "writing_start", "writer", "Writing the overview", None)
            body = ""
            async for delta in writer.write_report(question, synthesis, results, figures, sources,
                                                   ref_by_source, s.strong_model, api_key, persona=persona):
                body += delta
                await self._emit(job_id, live, "writing_chunk", "writer", delta, None)
            markdown = writer.finalize_markdown(body, figures, sources)
            await self._update(job_id, report_markdown=markdown)
            await self._emit(job_id, live, "report_complete", "writer", "Report ready",
                             {"markdown": markdown, "figures": [f.model_dump() for f in figures]})

            # 5. narrate
            progress.phase = "narrating"
            await self._update(job_id, status=ResearchStatus.NARRATING, progress=progress)
            await self._emit(job_id, live, "narration_start", "narration", f"Generating narration ({s.tts_voice})", None)
            try:
                script = writer.narration_script(markdown, figures)
                mp3 = await narration.synthesize_speech(script, api_key, s.tts_model, s.tts_voice, persona=persona)
                async with self._db.session() as session:
                    await SQLAlchemyResearchRepository(session).set_audio(
                        job_id, mp3, s.tts_voice, s.tts_model, narration.estimate_duration_s(script)
                    )
                    await session.commit()
                progress.has_audio = True
                await self._emit(job_id, live, "narration_complete", "narration", "Narration ready",
                                 {"voice": s.tts_voice, "bytes": len(mp3)})
            except Exception as exc:  # noqa: BLE001
                logger.exception("narration failed")
                await self._emit(job_id, live, "narration_failed", "narration",
                                 f"Narration failed: {str(exc)[:200]}", None)

            # done
            progress.phase = "complete"
            from datetime import datetime

            await self._update(job_id, status=ResearchStatus.COMPLETE, progress=progress,
                               completed_at=datetime.utcnow())
            await self._emit(job_id, live, "job_complete", None, "Done", {"has_audio": progress.has_audio})

        except asyncio.CancelledError:
            progress.phase = "failed"
            await self._update(job_id, status=ResearchStatus.FAILED, progress=progress, error="Cancelled")
            await self._emit(job_id, live, "job_failed", None, "Cancelled", None)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("research job %s failed", job_id)
            progress.phase = "failed"
            await self._update(job_id, status=ResearchStatus.FAILED, progress=progress, error=str(exc)[:500])
            await self._emit(job_id, live, "job_failed", None, str(exc)[:300], None)
        finally:
            live.done = True
            for q in list(live.subscribers):
                q.put_nowait(None)


# ---- module singleton ------------------------------------------------------

_runner: ResearchRunner | None = None


def set_runner(runner: ResearchRunner) -> None:
    global _runner
    _runner = runner


def get_runner() -> ResearchRunner:
    if _runner is None:
        raise RuntimeError("Research runner not initialised")
    return _runner


async def mark_interrupted_on_startup(database: Database) -> int:
    async with database.session() as session:
        n = await SQLAlchemyResearchRepository(session).mark_running_as_interrupted()
        await session.commit()
    if n:
        logger.warning("Marked %d research job(s) as interrupted after restart", n)
    return n
