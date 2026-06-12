"""Phase 7 part D: data lifecycle.

- `GET /projects/{id}/export` bundles report + deck + source list + audit log
  into one zip archive.
- Deleting a project cascades to every dependent table (verified on an engine
  with foreign keys enforced, as Postgres always does).
"""

import io
import json
import zipfile

import pytest_asyncio
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import (
    AuditLogEntry,
    BudgetLedgerEntry,
    Gap,
    PaperAnalysis,
    Presentation,
    Project,
    Provenance,
    Report,
    Run,
    Source,
    StageExecution,
    TraceEvent,
)
from tests.e2e.pipeline import e2e_engine, scripted_llm
from tests.orchestrator_utils import make_project
from tests.test_runner import RecordingBus, bus  # noqa: F401 — fixture reuse


@pytest_asyncio.fixture
async def fk_sessionmaker():
    """SQLite with foreign-key enforcement ON, mirroring Postgres cascades."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fks(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    await engine.dispose()


async def _run_pipeline(sessionmaker, bus) -> str:  # noqa: F811
    engine = e2e_engine(sessionmaker, bus, scripted_llm())
    project = await make_project(sessionmaker)
    run_id = await engine.start(project.id)
    await engine.execute(run_id)
    return project.id


async def test_export_bundle_contains_all_deliverables(sessionmaker, bus, client):  # noqa: F811
    project_id = await _run_pipeline(sessionmaker, bus)

    response = await client.get(f"/projects/{project_id}/export")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"

    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = set(archive.namelist())
    expected = {"manifest.json", "report-v1.md", "presentation.md", "sources.json"}
    expected.add("audit_log.json")
    assert names == expected

    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["project_id"] == project_id
    assert manifest["contents"] == {
        "report": True,
        "presentation": True,
        "sources": 4,
        "audit_entries": manifest["contents"]["audit_entries"],
    }
    assert manifest["contents"]["audit_entries"] > 10

    sources = json.loads(archive.read("sources.json"))
    assert len(sources) == 4
    assert all(s["triage_status"] for s in sources)

    audit = json.loads(archive.read("audit_log.json"))
    actions = {entry["action_type"] for entry in audit}
    assert {"stage_start", "stage_complete", "paper_analyzed", "report_drafted"} <= actions

    report_md = archive.read("report-v1.md").decode()
    assert "References" in report_md or "confidence" in report_md


async def test_project_delete_cascades_everywhere(fk_sessionmaker, bus):  # noqa: F811
    project_id = await _run_pipeline(fk_sessionmaker, bus)

    async with fk_sessionmaker() as session:
        project = await session.get(Project, project_id)
        await session.delete(project)
        await session.commit()

    dependents = [
        Source,
        Run,
        StageExecution,
        BudgetLedgerEntry,
        TraceEvent,
        PaperAnalysis,
        Provenance,
        Gap,
        Report,
        Presentation,
        AuditLogEntry,
    ]
    async with fk_sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(Project)) == 0
        for model in dependents:
            count = await session.scalar(select(func.count()).select_from(model))
            assert count == 0, f"{model.__name__} rows survived the project delete"
