"""SQLAlchemy models for Deep Research jobs, figures and narration audio.

Imported from `persistence/__init__.py` so `Base.metadata.create_all` at
startup creates the tables; there is no migration tool in this project.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agent_system.adapters.outbound.persistence.database import Base


class ResearchJobModel(Base):
    __tablename__ = "research_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    progress: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Append-only stream events for replay (writing chunks are not persisted;
    # the finished report is).
    events: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    tldr: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    figures: Mapped[list["ResearchFigureModel"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="ResearchFigureModel.ordinal"
    )
    audio: Mapped["ResearchAudioModel | None"] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False
    )


class ResearchFigureModel(Base):
    __tablename__ = "research_figures"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("research_jobs.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    caption: Mapped[str] = mapped_column(Text, default="")
    chart_spec: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    png: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    job: Mapped["ResearchJobModel"] = relationship(back_populates="figures")


class ResearchAudioModel(Base):
    __tablename__ = "research_audio"

    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("research_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    mp3: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    voice: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    job: Mapped["ResearchJobModel"] = relationship(back_populates="audio")
