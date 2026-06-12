"""Run lifecycle + escalation REST endpoints (Phase 1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import BudgetCategory, ProjectStatus
from app.core.errors import NotFound, ValidationError
from app.db.models import Escalation, Project, Run
from app.db.session import get_session
from app.orchestrator.escalation import resolve_escalation
from app.orchestrator.runner import RunEngine, get_run_engine
from app.schemas.runs import (
    BudgetAdjustBody,
    EscalationRead,
    ResolveEscalationBody,
    RunRead,
    RunStartResponse,
    StopRunBody,
)

router = APIRouter(tags=["runs"])


@router.post(
    "/projects/{project_id}/runs",
    response_model=RunStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_run(project_id: str) -> RunStartResponse:
    engine = get_run_engine()
    run_id = await engine.start(project_id)
    engine.launch(run_id)
    return RunStartResponse(run_id=run_id)


@router.get("/projects/{project_id}/runs", response_model=list[RunRead])
async def list_runs(project_id: str, session: AsyncSession = Depends(get_session)) -> list[RunRead]:
    if await session.get(Project, project_id) is None:
        raise NotFound(f"Project {project_id} not found")
    result = await session.execute(
        select(Run).where(Run.project_id == project_id).order_by(Run.started_at.desc())
    )
    return [RunRead.model_validate(r) for r in result.scalars().all()]


@router.get("/runs/{run_id}", response_model=RunRead)
async def get_run(run_id: str, session: AsyncSession = Depends(get_session)) -> RunRead:
    run = await session.get(Run, run_id)
    if run is None:
        raise NotFound(f"Run {run_id} not found")
    return RunRead.model_validate(run)


@router.post("/runs/{run_id}/pause", response_model=RunRead)
async def pause_run(run_id: str) -> RunRead:
    engine = get_run_engine()
    await engine.pause(run_id)
    return await _read_run(engine, run_id)


@router.post("/runs/{run_id}/resume", response_model=RunRead)
async def resume_run(run_id: str) -> RunRead:
    engine = get_run_engine()
    await engine.resume(run_id)
    engine.launch(run_id)
    return await _read_run(engine, run_id)


@router.post("/runs/{run_id}/stop", response_model=RunRead)
async def stop_run(run_id: str, body: StopRunBody | None = None) -> RunRead:
    engine = get_run_engine()
    await engine.stop(run_id, reason=body.reason if body else None)
    return await _read_run(engine, run_id)


@router.post("/runs/{run_id}/budget", response_model=RunRead)
async def adjust_budget(
    run_id: str, body: BudgetAdjustBody, session: AsyncSession = Depends(get_session)
) -> RunRead:
    """Adjust ceilings mid-run. Ceilings live on the project's budget; the
    engine re-reads them at each stage step."""
    run = await session.get(Run, run_id)
    if run is None:
        raise NotFound(f"Run {run_id} not found")
    project = await session.get(Project, run.project_id)
    if project is None:
        raise NotFound(f"Project {run.project_id} not found")
    overrides = {
        category: value
        for category, value in body.model_dump().items()
        if value is not None and category in {c.value for c in BudgetCategory}
    }
    if not overrides:
        raise ValidationError("No budget categories provided")
    project.budget = {**(project.budget or {}), **overrides}
    await session.flush()
    return RunRead.model_validate(run)


@router.get("/projects/{project_id}/escalations", response_model=list[EscalationRead])
async def list_escalations(
    project_id: str,
    status_filter: str | None = Query(default=None, alias="status"),
    session: AsyncSession = Depends(get_session),
) -> list[EscalationRead]:
    if await session.get(Project, project_id) is None:
        raise NotFound(f"Project {project_id} not found")
    query = select(Escalation).where(Escalation.project_id == project_id)
    if status_filter:
        query = query.where(Escalation.status == status_filter)
    result = await session.execute(query.order_by(Escalation.created_at.desc()))
    return [EscalationRead.model_validate(e) for e in result.scalars().all()]


@router.post("/escalations/{escalation_id}/resolve", response_model=EscalationRead)
async def resolve(
    escalation_id: str,
    body: ResolveEscalationBody,
    session: AsyncSession = Depends(get_session),
) -> EscalationRead:
    escalation = await resolve_escalation(session, escalation_id, body.user_response)
    response = EscalationRead.model_validate(escalation)
    await session.commit()

    # Re-queue the paused run so the raising stage resumes with the response.
    if escalation.run_id is not None:
        engine = get_run_engine()
        await engine.resume(escalation.run_id)
        engine.launch(escalation.run_id)
    else:
        project = await session.get(Project, escalation.project_id)
        if project is not None and project.status == ProjectStatus.awaiting_input.value:
            project.status = ProjectStatus.running.value
    return response


async def _read_run(engine: RunEngine, run_id: str) -> RunRead:
    async with engine.sessionmaker()() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise NotFound(f"Run {run_id} not found")
        return RunRead.model_validate(run)
