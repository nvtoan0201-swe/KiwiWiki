"""FastAPI application factory.

Wires middleware, exception handlers, routers, and startup/shutdown lifecycle.
Run from the backend/ directory:

    uvicorn app.main:app --reload
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import audit, health, insights, presentations, projects, reports, runs, sources, ws
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import RequestIdMiddleware, configure_logging
from app.db.session import dispose_engine
from app.events.bus import get_event_bus


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    # Initialize the event bus (Redis or in-memory fallback) eagerly so the
    # WS endpoint and audit publishes share one instance.
    get_event_bus()
    yield
    bus = get_event_bus()
    await bus.close()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Autonomous Research Agent", version="0.1.0", lifespan=lifespan)

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(projects.router)
    app.include_router(audit.router)
    app.include_router(runs.router)
    app.include_router(sources.router)
    app.include_router(insights.router)
    app.include_router(reports.router)
    app.include_router(presentations.router)
    app.include_router(ws.router)
    return app


app = create_app()
