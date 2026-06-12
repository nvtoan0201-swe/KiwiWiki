"""A disposable in-memory world for eval checks: sqlite DB, in-memory event
bus, and direct StageContext construction — no Postgres, Redis, or network."""

from __future__ import annotations

import datetime
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401 — register tables on metadata
from app.adapters.embeddings.client import EmbeddingsClient
from app.core.config import get_settings
from app.core.constants import Stage
from app.db.base import Base
from app.db.models import Project, Run, StageExecution
from app.events.bus import InMemoryEventBus, set_event_bus
from app.events.publisher import EventPublisher
from app.orchestrator.budget import BudgetGuard
from app.orchestrator.handler import StageContext
from app.services.audit import AuditService
from tests.llm_fakes import FakeLLM, llm_factory
from tests.test_runner import RecordingBus


@dataclass(slots=True)
class World:
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    bus: RecordingBus


@asynccontextmanager
async def world() -> AsyncIterator[World]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    bus = RecordingBus()
    set_event_bus(bus)
    try:
        yield World(
            engine=engine,
            sessionmaker=async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession),
            bus=bus,
        )
    finally:
        await engine.dispose()


@contextmanager
def override_settings(**overrides: Any) -> Iterator[None]:
    """Temporarily change settings on the cached Settings instance."""
    settings = get_settings()
    saved = {key: getattr(settings, key) for key in overrides}
    for key, value in overrides.items():
        setattr(settings, key, value)
    try:
        yield
    finally:
        for key, value in saved.items():
            setattr(settings, key, value)


async def make_stage_ctx(
    session: AsyncSession,
    bus: InMemoryEventBus,
    project: Project,
    stage: Stage,
    fake_llm: FakeLLM,
    *,
    embeddings: EmbeddingsClient,
) -> StageContext:
    """A StageContext for driving one handler directly (outside the engine)."""
    run = Run(project_id=project.id, status="running")
    session.add(run)
    await session.flush()
    execution = StageExecution(
        run_id=run.id,
        stage=stage.value,
        status="running",
        started_at=datetime.datetime.now(datetime.UTC),
    )
    session.add(execution)
    await session.flush()
    audit = AuditService(session, bus)
    events = EventPublisher(bus, project.id, run.id)
    guard = await BudgetGuard.create(session, run, project, audit, events, stage=stage.value)
    return StageContext(
        session=session,
        project=project,
        run=run,
        stage_execution=execution,
        budget=guard,
        audit=audit,
        events=events,
        embeddings=embeddings,
        llm_factory=llm_factory(fake_llm),
    )
