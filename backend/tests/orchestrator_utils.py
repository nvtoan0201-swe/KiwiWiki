"""Shared helpers for orchestrator tests: project factory, stub registries, and
an engine wired to the in-memory bus + sqlite sessionmaker."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import Stage
from app.db.models import Project
from app.events.bus import InMemoryEventBus
from app.orchestrator.registry import StageRegistry
from app.orchestrator.runner import RunEngine
from app.stages._stubs import StubBehavior, StubStageHandler

ALL_STAGES = list(Stage)


async def make_project(sessionmaker: async_sessionmaker[AsyncSession], **overrides: Any) -> Project:
    fields: dict[str, Any] = {
        "title": "Test project",
        "original_request": "How do transformers compare to RNNs for time-series forecasting?",
        "status": "draft",
    }
    fields.update(overrides)
    async with sessionmaker() as session:
        project = Project(**fields)
        session.add(project)
        await session.commit()
        return project


def stub_registry(
    behaviors: dict[Stage, StubBehavior] | None = None,
) -> tuple[StageRegistry, dict[Stage, StubStageHandler]]:
    behaviors = behaviors or {}
    registry = StageRegistry()
    handlers: dict[Stage, StubStageHandler] = {}
    for stage in ALL_STAGES:
        handler = StubStageHandler(stage, behaviors.get(stage))
        registry.register(handler)
        handlers[stage] = handler
    return registry, handlers


def make_engine(
    sessionmaker: async_sessionmaker[AsyncSession],
    bus: InMemoryEventBus,
    registry: StageRegistry,
    **kwargs: Any,
) -> RunEngine:
    return RunEngine(sessionmaker, registry=registry, bus=bus, **kwargs)
