"""SQLAlchemy repository for the journal.

Every method takes the owner's `user_id` and puts it in the WHERE clause, so a
caller cannot read or change another user's journal even with a valid id.
"""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_system.adapters.outbound.persistence.journal_models import JournalEntryModel, JournalMessageModel


class SQLAlchemyJournalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- entries ----------------------------------------------------------

    async def create_entry(self, user_id: str, entry_date: str, body: str) -> JournalEntryModel:
        now = datetime.utcnow()
        entry = JournalEntryModel(id=str(uuid4()), user_id=user_id, entry_date=entry_date, body=body,
                                  suggestions=[], memory_status="pending", created_at=now, updated_at=now)
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def get_entry(self, entry_id: str, user_id: str) -> JournalEntryModel | None:
        stmt = select(JournalEntryModel).where(JournalEntryModel.id == entry_id, JournalEntryModel.user_id == user_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def entries_for_day(self, user_id: str, entry_date: str) -> list[JournalEntryModel]:
        stmt = (
            select(JournalEntryModel)
            .where(JournalEntryModel.user_id == user_id, JournalEntryModel.entry_date == entry_date)
            .order_by(JournalEntryModel.created_at)
        )
        return list((await self._session.execute(stmt)).scalars())

    async def find_entries(
        self,
        user_id: str,
        *,
        start: str | None = None,
        end: str | None = None,
        search: str | None = None,
        limit: int = 20,
    ) -> list[JournalEntryModel]:
        """Entries in an inclusive day range and/or containing every search word, newest first."""
        stmt = select(JournalEntryModel).where(JournalEntryModel.user_id == user_id)
        if start:
            stmt = stmt.where(JournalEntryModel.entry_date >= start)
        if end:
            stmt = stmt.where(JournalEntryModel.entry_date <= end)
        for word in (search or "").split()[:6]:
            escaped = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            stmt = stmt.where(or_(JournalEntryModel.body.ilike(f"%{escaped}%", escape="\\")))
        stmt = stmt.order_by(JournalEntryModel.entry_date.desc(), JournalEntryModel.created_at.desc()).limit(limit)
        return list((await self._session.execute(stmt)).scalars())

    async def day_counts(self, user_id: str, start: str, end: str) -> dict[str, int]:
        """{day: number of entries} for an inclusive day range."""
        stmt = (
            select(JournalEntryModel.entry_date, func.count())
            .where(JournalEntryModel.user_id == user_id, JournalEntryModel.entry_date >= start,
                   JournalEntryModel.entry_date <= end)
            .group_by(JournalEntryModel.entry_date)
        )
        return {day: count for day, count in (await self._session.execute(stmt)).all()}

    async def update_entry(self, entry_id: str, user_id: str, **fields: Any) -> JournalEntryModel | None:
        entry = await self.get_entry(entry_id, user_id)
        if entry is None:
            return None
        for name, value in fields.items():
            setattr(entry, name, value)
        if "body" in fields:
            entry.updated_at = datetime.utcnow()
        await self._session.flush()
        return entry

    async def delete_entry(self, entry_id: str, user_id: str) -> bool:
        stmt = delete(JournalEntryModel).where(JournalEntryModel.id == entry_id, JournalEntryModel.user_id == user_id)
        return (await self._session.execute(stmt)).rowcount > 0

    # ---- side chat --------------------------------------------------------

    async def add_message(self, user_id: str, entry_date: str, role: str, content: str,
                          tools_used: list[str] | None = None) -> JournalMessageModel:
        message = JournalMessageModel(id=str(uuid4()), user_id=user_id, entry_date=entry_date, role=role,
                                      content=content, tools_used=tools_used or [])
        self._session.add(message)
        await self._session.flush()
        return message

    async def messages_for_day(self, user_id: str, entry_date: str, limit: int = 200) -> list[JournalMessageModel]:
        stmt = (
            select(JournalMessageModel)
            .where(JournalMessageModel.user_id == user_id, JournalMessageModel.entry_date == entry_date)
            .order_by(JournalMessageModel.created_at.desc())
            .limit(limit)
        )
        return list(reversed(list((await self._session.execute(stmt)).scalars())))

    async def clear_messages(self, user_id: str, entry_date: str) -> int:
        stmt = delete(JournalMessageModel).where(JournalMessageModel.user_id == user_id,
                                                 JournalMessageModel.entry_date == entry_date)
        return (await self._session.execute(stmt)).rowcount
