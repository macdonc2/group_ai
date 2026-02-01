"""Database configuration and session management."""

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


class Database:
    """Database connection and session management."""

    def __init__(self, url: str, echo: bool = False) -> None:
        """Initialize database with connection URL.
        
        Args:
            url: SQLAlchemy connection URL
            echo: Whether to echo SQL statements
        """
        self._engine = create_async_engine(
            url,
            echo=echo,
            pool_pre_ping=True,
        )
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def create_tables(self) -> None:
        """Create all tables in the database."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def drop_tables(self) -> None:
        """Drop all tables in the database."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session."""
        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    def session(self) -> AsyncSession:
        """Create a new session (caller responsible for commit/rollback)."""
        return self._session_factory()

    async def dispose(self) -> None:
        """Dispose of the database engine."""
        await self._engine.dispose()

    @property
    def engine(self) -> Any:
        """Get the SQLAlchemy engine."""
        return self._engine
