from __future__ import annotations

import asyncio

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from backend.app.core.config import settings


_ENGINES_BY_LOOP: dict[int, AsyncEngine] = {}


def get_engine() -> AsyncEngine:
    """Return an AsyncEngine scoped to the current event loop.

    On Windows/pytest it's common to have multiple event loops across tests; reusing the
    same asyncpg connections across loops can fail with "Event loop is closed".
    """

    loop_id = id(asyncio.get_running_loop())
    eng = _ENGINES_BY_LOOP.get(loop_id)
    if eng is None:
        eng = create_async_engine(settings.database_url, pool_pre_ping=True)
        _ENGINES_BY_LOOP[loop_id] = eng
    return eng


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    engine = get_engine()
    SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
