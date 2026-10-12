"""Async SQLAlchemy engine/session management and the transaction helper."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(s.DATABASE_URL, pool_size=s.DB_POOL_SIZE,
                                      max_overflow=s.DB_MAX_OVERFLOW, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Rolls back anything left uncommitted."""
    async with get_sessionmaker()() as session:
        try:
            yield session
        finally:
            if session.in_transaction():
                await session.rollback()


@asynccontextmanager
async def transactional(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """Service-owned transaction boundary: commit on success, rollback on any error.

    Works even if a prior read auto-began a transaction (e.g. auth dependency).
    Audit rows MUST be added inside this block so they commit atomically with the action.
    """
    try:
        yield session
        await session.commit()
    except BaseException:
        await session.rollback()
        raise


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine, _sessionmaker = None, None
