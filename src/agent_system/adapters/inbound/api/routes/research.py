"""Deep Research API: durable jobs, live stream, figures, narration."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Header, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse

from agent_system.adapters.inbound.api.auth import decode_access_token
from agent_system.adapters.inbound.api.dependencies import CurrentUserId, SessionDep
from agent_system.adapters.inbound.api.schemas import (
    FigureRead,
    ResearchCreate,
    ResearchDetail,
    ResearchListItem,
    SourceRead,
)
from agent_system.adapters.outbound.llm.personas import is_valid_persona
from agent_system.adapters.outbound.persistence import SQLAlchemyUserRepository
from agent_system.adapters.outbound.persistence.research_repositories import (
    SQLAlchemyResearchRepository,
)
from agent_system.adapters.outbound.research import get_runner
from agent_system.adapters.outbound.research.runner import TERMINAL_EVENTS
from agent_system.domain.entities.research import ResearchJob, ResearchStatus
from agent_system.domain.value_objects import UserId

router = APIRouter(prefix="/research", tags=["research"])
logger = logging.getLogger(__name__)


def _resolve_api_key(user, settings) -> str:
    """System key first, else the user's encrypted key. Never touches os.environ."""
    if settings.openai_api_key:
        return settings.openai_api_key
    if user.has_api_key():
        from agent_system.domain.utils.encryption import get_api_key_encryption

        return get_api_key_encryption().decrypt(user.encrypted_openai_api_key)
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="No OpenAI API key available. Add one under Settings → API key.",
    )


def _user_from_query_or_header(token: str | None, authorization: str | None) -> str:
    """<img>/<audio> tags can't send headers; accept ?token= as well."""
    raw = token
    if not raw and authorization and authorization.lower().startswith("bearer "):
        raw = authorization.split(" ", 1)[1]
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token required")
    data = decode_access_token(raw)
    if data is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return data.user_id


def _list_item(job: ResearchJob, has_audio: bool = False) -> ResearchListItem:
    return ResearchListItem(
        id=job.id, question=job.question, title=job.title, status=job.status.value,
        phase=job.progress.phase, created_at=job.created_at, completed_at=job.completed_at,
        has_audio=has_audio or job.progress.has_audio, figures=job.progress.figures,
        depth=job.progress.depth, persona=job.progress.persona, error=job.error,
    )


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_research(payload: ResearchCreate, current_user_id: CurrentUserId, session: SessionDep) -> ResearchListItem:
    from agent_system.composition_root.config import get_settings

    settings = get_settings()
    user = await SQLAlchemyUserRepository(session).get(UserId.from_string(current_user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    api_key = _resolve_api_key(user, settings)

    repo = SQLAlchemyResearchRepository(session)
    job = await repo.create(current_user_id, payload.question.strip(), settings.default_model)
    progress = job.progress
    progress.depth = payload.depth
    progress.persona = payload.persona.strip().lower() if is_valid_persona(payload.persona) else None
    await repo.update_fields(job.id, progress=progress)
    await session.commit()
    job.progress = progress

    get_runner().start(job.id, api_key)
    return _list_item(job)


@router.get("")
async def list_research(current_user_id: CurrentUserId, session: SessionDep) -> list[ResearchListItem]:
    repo = SQLAlchemyResearchRepository(session)
    return [_list_item(j) for j in await repo.list_for_user(current_user_id)]


@router.get("/{job_id}")
async def get_research(job_id: str, current_user_id: CurrentUserId, session: SessionDep) -> ResearchDetail:
    repo = SQLAlchemyResearchRepository(session)
    job = await repo.get(job_id, current_user_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research job not found")
    figures = await repo.list_figures(job_id)
    has_audio = await repo.has_audio(job_id)
    return ResearchDetail(
        **_list_item(job, has_audio).model_dump(),
        tldr=job.tldr,
        report_markdown=job.report_markdown,
        progress=job.progress.model_dump(),
        model=job.model,
        sources=[SourceRead(**s.model_dump()) for s in job.sources],
        figure_list=[FigureRead(ordinal=f.ordinal, caption=f.caption, source_ids=f.source_ids, origin=f.origin,
                                source_url=f.source_url, source_title=f.source_title) for f in figures],
    )


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_research(job_id: str, current_user_id: CurrentUserId, session: SessionDep) -> None:
    await get_runner().cancel(job_id)
    if not await SQLAlchemyResearchRepository(session).delete(job_id, current_user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research job not found")


@router.post("/{job_id}/cancel")
async def cancel_research(job_id: str, current_user_id: CurrentUserId, session: SessionDep) -> ResearchListItem:
    repo = SQLAlchemyResearchRepository(session)
    job = await repo.get(job_id, current_user_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research job not found")
    await get_runner().cancel(job_id)
    return _list_item(job)


@router.get("/{job_id}/stream")
async def stream_research(
    job_id: str,
    session: SessionDep,
    token: str | None = Query(None, description="Auth token (EventSource cannot send headers)"),
    after: int = Query(0, description="Replay only events with seq greater than this"),
) -> StreamingResponse:
    """Replay persisted events, then tail live ones until the job ends."""
    user_id = _user_from_query_or_header(token, None)
    repo = SQLAlchemyResearchRepository(session)
    job = await repo.get(job_id, user_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research job not found")

    runner = get_runner()
    # Subscribe BEFORE reading history so nothing falls in the gap; dedupe by seq.
    live_q = runner.subscribe(job_id)
    history = await repo.get_events(job_id)

    async def gen() -> AsyncGenerator[str, None]:
        last_seq = after
        try:
            for ev in history:
                seq = (ev.get("data") or {}).get("seq", 0)
                if seq <= last_seq:
                    continue
                last_seq = seq
                yield f"data: {json.dumps(ev)}\n\n"
                if ev["event_type"] in TERMINAL_EVENTS:
                    return
            if job.status in (ResearchStatus.COMPLETE, ResearchStatus.FAILED, ResearchStatus.INTERRUPTED):
                # Finished (or died) before anyone was listening: close cleanly.
                terminal = {"job_complete": "complete", "job_failed": "failed", "job_interrupted": "interrupted"}
                name = next((k for k, v in terminal.items() if v == job.status.value), "job_interrupted")
                yield f"data: {json.dumps({'event_type': name, 'node_name': None, 'message': job.error or job.status.value, 'data': {'seq': last_seq}, 'timestamp': 0})}\n\n"
                return
            if live_q is None:
                # Not running in this process (another replica, or restarted).
                yield f"data: {json.dumps({'event_type': 'job_interrupted', 'node_name': None, 'message': 'This run is not active on the server. Run it again.', 'data': {'seq': last_seq}, 'timestamp': 0})}\n\n"
                return
            while True:
                try:
                    ev = await asyncio.wait_for(live_q.get(), timeout=25)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if ev is None:
                    return
                seq = (ev.get("data") or {}).get("seq", 0)
                if seq <= last_seq:
                    continue
                last_seq = seq
                yield f"data: {json.dumps(ev)}\n\n"
                if ev["event_type"] in TERMINAL_EVENTS:
                    return
        finally:
            if live_q is not None:
                runner.unsubscribe(job_id, live_q)

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/{job_id}/figures/{ordinal}")
async def get_figure(
    job_id: str, ordinal: int, session: SessionDep,
    token: str | None = Query(None), authorization: str | None = Header(None),
) -> Response:
    user_id = _user_from_query_or_header(token, authorization)
    repo = SQLAlchemyResearchRepository(session)
    if not await repo.get(job_id, user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research job not found")
    png = await repo.get_figure_png(job_id, ordinal)
    if png is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Figure not found")
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/{job_id}/audio")
async def get_audio(
    job_id: str, session: SessionDep,
    token: str | None = Query(None), authorization: str | None = Header(None),
) -> Response:
    user_id = _user_from_query_or_header(token, authorization)
    repo = SQLAlchemyResearchRepository(session)
    if not await repo.get(job_id, user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research job not found")
    found = await repo.get_audio(job_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Narration not generated yet")
    mp3, _voice = found
    return Response(
        content=mp3, media_type="audio/mpeg",
        headers={"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=86400",
                 "Content-Disposition": f'inline; filename="research-{job_id[:8]}.mp3"'},
    )


@router.post("/{job_id}/narrate", status_code=status.HTTP_202_ACCEPTED)
async def regenerate_narration(job_id: str, current_user_id: CurrentUserId, session: SessionDep) -> dict:
    """Re-run just the narration for a finished report."""
    from agent_system.adapters.outbound.research import narration, writer
    from agent_system.composition_root.config import get_settings

    settings = get_settings()
    repo = SQLAlchemyResearchRepository(session)
    job = await repo.get(job_id, current_user_id)
    if not job or not job.report_markdown:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No finished report to narrate")
    user = await SQLAlchemyUserRepository(session).get(UserId.from_string(current_user_id))
    api_key = _resolve_api_key(user, settings)
    figures = await repo.list_figures(job_id)
    script = writer.narration_script(job.report_markdown, figures)
    mp3 = await narration.synthesize_speech(script, api_key, settings.tts_model, settings.tts_voice, persona=job.progress.persona)
    await repo.set_audio(job_id, mp3, settings.tts_voice, settings.tts_model, narration.estimate_duration_s(script))
    progress = job.progress
    progress.has_audio = True
    await repo.update_fields(job_id, progress=progress)
    return {"status": "ok", "bytes": len(mp3), "voice": settings.tts_voice}
