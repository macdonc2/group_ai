"""SQLAlchemy models for the journal: dated entries and the per-day side chat.

Imported from `persistence/__init__.py` so `Base.metadata.create_all` at
startup creates the tables; there is no migration tool in this project, so
these are new tables rather than new columns on `conversations`.

Postgres is the source of truth for journal text. The knowledge graph and the
message embeddings hold a derived copy that is rebuilt on edit and removed on
delete (see `adapters/outbound/llm/journal_memory.py`).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from agent_system.adapters.outbound.persistence.database import Base


class JournalEntryModel(Base):
    """One piece of the user's own writing, filed under a calendar day."""

    __tablename__ = "journal_entries"
    __table_args__ = (Index("ix_journal_entries_user_day", "user_id", "entry_date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # The day the entry belongs to, as the user saw it ("2026-11-13"). Decided once,
    # in the user's timezone at the time of writing, and never recomputed: changing
    # the timezone setting later must not move old entries to a different day.
    entry_date: Mapped[str] = mapped_column(String(10))
    body: Mapped[str] = mapped_column(Text)
    # Possible calendar events found in the entry, waiting for the user's click:
    # [{"id", "title", "when", "location", "status": "pending"|"added"|"dismissed"}]
    suggestions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # State of the derived memory: "pending" | "done" | "failed" | "skipped"
    memory_status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # When the text last changed. Set by the repository only for a text change, so
    # background memory and suggestion updates do not make an entry look edited.
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class JournalMessageModel(Base):
    """One message of the side chat about a day. Never treated as journal text."""

    __tablename__ = "journal_messages"
    __table_args__ = (Index("ix_journal_messages_user_day", "user_id", "entry_date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    entry_date: Mapped[str] = mapped_column(String(10))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    tools_used: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
