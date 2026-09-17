"""SQLAlchemy repository for Deep Research jobs.

Deliberately lighter than the mapper-based repositories: the job is mostly
JSON, and the runner writes small updates from a background task with a
short-lived session per write.
"""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agent_system.adapters.outbound.persistence.research_models import (
    ResearchAudioModel,
    ResearchFigureModel,
    ResearchJobModel,
)
from agent_system.domain.entities.research import (
    Figure,
    ResearchJob,
    ResearchProgress,
    ResearchStatus,
    Source,
)


def _to_entity(m: ResearchJobModel) -> ResearchJob:
    return ResearchJob(
        id=m.id,
        user_id=m.user_id,
        question=m.question,
        status=ResearchStatus(m.status),
        progress=ResearchProgress.model_validate(m.progress or {}),
        model=m.model or "",
        title=m.title,
        tldr=m.tldr,
        report_markdown=m.report_markdown,
        sources=[Source.model_validate(s) for s in (m.sources or [])],
        error=m.error,
        created_at=m.created_at,
        updated_at=m.updated_at,
        completed_at=m.completed_at,
    )


class SQLAlchemyResearchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- jobs -------------------------------------------------------------

    async def create(self, user_id: str, question: str, model: str) -> ResearchJob:
        m = ResearchJobModel(
            id=str(uuid4()),
            user_id=user_id,
            question=question,
            status=ResearchStatus.QUEUED.value,
            progress=ResearchProgress().model_dump(),
            events=[],
            model=model,
        )
        self._session.add(m)
        await self._session.flush()
        return _to_entity(m)

    async def get(self, job_id: str, user_id: str | None = None) -> ResearchJob | None:
        stmt = select(ResearchJobModel).where(ResearchJobModel.id == job_id)
        if user_id is not None:
            stmt = stmt.where(ResearchJobModel.user_id == user_id)
        m = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_entity(m) if m else None

    async def list_for_user(self, user_id: str, limit: int = 50) -> list[ResearchJob]:
        stmt = (
            select(ResearchJobModel)
            .where(ResearchJobModel.user_id == user_id)
            .order_by(ResearchJobModel.created_at.desc())
            .limit(limit)
        )
        return [_to_entity(m) for m in (await self._session.execute(stmt)).scalars().all()]

    async def delete(self, job_id: str, user_id: str) -> bool:
        result = await self._session.execute(
            delete(ResearchJobModel).where(
                ResearchJobModel.id == job_id, ResearchJobModel.user_id == user_id
            )
        )
        return (result.rowcount or 0) > 0

    async def update_fields(self, job_id: str, **fields: Any) -> None:
        fields["updated_at"] = datetime.utcnow()
        if "status" in fields and isinstance(fields["status"], ResearchStatus):
            fields["status"] = fields["status"].value
        if "progress" in fields and isinstance(fields["progress"], ResearchProgress):
            fields["progress"] = fields["progress"].model_dump()
        if "sources" in fields:
            fields["sources"] = [
                s.model_dump() if isinstance(s, Source) else s for s in fields["sources"]
            ]
        await self._session.execute(
            update(ResearchJobModel).where(ResearchJobModel.id == job_id).values(**fields)
        )

    async def append_event(self, job_id: str, event: dict[str, Any]) -> None:
        m = (
            await self._session.execute(
                select(ResearchJobModel).where(ResearchJobModel.id == job_id)
            )
        ).scalar_one_or_none()
        if not m:
            return
        # Reassign so SQLAlchemy sees the JSON column change.
        m.events = [*(m.events or []), event]
        m.updated_at = datetime.utcnow()
        await self._session.flush()

    async def get_events(self, job_id: str) -> list[dict[str, Any]]:
        m = (
            await self._session.execute(
                select(ResearchJobModel.events).where(ResearchJobModel.id == job_id)
            )
        ).scalar_one_or_none()
        return list(m or [])

    async def mark_running_as_interrupted(self) -> int:
        """On process start: nothing survives a restart, say so on the row."""
        live = [
            ResearchStatus.QUEUED.value,
            ResearchStatus.RUNNING.value,
            ResearchStatus.SYNTHESIZING.value,
            ResearchStatus.WRITING.value,
            ResearchStatus.NARRATING.value,
        ]
        result = await self._session.execute(
            update(ResearchJobModel)
            .where(ResearchJobModel.status.in_(live))
            .values(
                status=ResearchStatus.INTERRUPTED.value,
                error="The server restarted while this run was in progress. Run it again.",
                updated_at=datetime.utcnow(),
            )
        )
        return result.rowcount or 0

    # ---- figures ----------------------------------------------------------

    async def add_figure(self, job_id: str, figure: Figure, png: bytes) -> str:
        spec = dict(figure.chart_spec)
        spec["_meta"] = {"origin": figure.origin, "source_url": figure.source_url, "source_title": figure.source_title}
        m = ResearchFigureModel(
            id=str(uuid4()),
            job_id=job_id,
            ordinal=figure.ordinal,
            caption=figure.caption,
            chart_spec=spec,
            source_ids=figure.source_ids,
            png=png,
        )
        self._session.add(m)
        await self._session.flush()
        return m.id

    async def list_figures(self, job_id: str) -> list[Figure]:
        stmt = (
            select(ResearchFigureModel)
            .where(ResearchFigureModel.job_id == job_id)
            .order_by(ResearchFigureModel.ordinal)
        )
        out = []
        for f in (await self._session.execute(stmt)).scalars().all():
            spec = dict(f.chart_spec or {})
            meta = spec.pop("_meta", {}) or {}
            out.append(Figure(
                ordinal=f.ordinal, caption=f.caption, chart_spec=spec, source_ids=f.source_ids or [],
                origin=meta.get("origin", "generated"), source_url=meta.get("source_url"),
                source_title=meta.get("source_title"),
            ))
        return out

    async def get_figure_png(self, job_id: str, ordinal: int) -> bytes | None:
        stmt = select(ResearchFigureModel.png).where(
            ResearchFigureModel.job_id == job_id, ResearchFigureModel.ordinal == ordinal
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    # ---- audio ------------------------------------------------------------

    async def set_audio(
        self, job_id: str, mp3: bytes, voice: str, model: str, duration_s: float | None
    ) -> None:
        await self._session.execute(
            delete(ResearchAudioModel).where(ResearchAudioModel.job_id == job_id)
        )
        self._session.add(
            ResearchAudioModel(job_id=job_id, mp3=mp3, voice=voice, model=model, duration_s=duration_s)
        )
        await self._session.flush()

    async def get_audio(self, job_id: str) -> tuple[bytes, str] | None:
        m = (
            await self._session.execute(
                select(ResearchAudioModel).where(ResearchAudioModel.job_id == job_id)
            )
        ).scalar_one_or_none()
        return (m.mp3, m.voice) if m else None

    async def has_audio(self, job_id: str) -> bool:
        stmt = select(ResearchAudioModel.job_id).where(ResearchAudioModel.job_id == job_id)
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None
