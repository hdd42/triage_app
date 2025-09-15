from __future__ import annotations

import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy import text

Base = declarative_base()

_engine: AsyncEngine | None = None
_SessionFactory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./app.db")
        _engine = create_async_engine(
            database_url,
            future=True,
            echo=False,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    return _SessionFactory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async_session = get_session_factory()
    async with async_session() as session:
        yield session


async def init_db() -> None:
    """
    Initialize the database by creating tables.
    Import models to ensure metadata is populated, then create_all.
    """
    # Import models to register metadata
    import models  # noqa: F401

    engine = get_engine()
    async with engine.begin() as conn:
        # Ensure SQLite has foreign key support ON
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        await conn.run_sync(Base.metadata.create_all)
