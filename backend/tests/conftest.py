"""Shared test fixtures.

Tests run against an in-memory SQLite database (the model column variants make
this portable) and the in-memory event bus, so no Postgres/Redis is required.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401 — register tables on metadata
from app.db.base import Base
from app.db.session import get_session
from app.events.bus import InMemoryEventBus, set_event_bus


@pytest_asyncio.fixture
async def engine() -> AsyncIterator:
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def sessionmaker(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture
async def session(sessionmaker) -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as s:
        yield s


@pytest.fixture
def event_bus() -> InMemoryEventBus:
    bus = InMemoryEventBus()
    set_event_bus(bus)
    return bus


@pytest_asyncio.fixture
async def client(sessionmaker, event_bus) -> AsyncIterator[AsyncClient]:
    # Import here so the app picks up the injected event bus.
    from app.main import app

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
