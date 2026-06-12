"""Run lifecycle + escalation REST endpoints (Phase 1) and the per-run trace
(Phase 7 part C)."""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AuditActionType, BudgetCategory, ProjectStatus
from app.core.errors import NotFound, ValidationError
from app.db.models import (
    AuditLogEntry,
    BudgetLedgerEntry,
    Escalation,
    Project,
    Run,
    StageExecution,
    TraceEvent,
)
from app.db.session import get_session
from app.orchestrator.escalation import resolve_escalation
from app.orchestrator.runner import RunEngine, get_run_engine
from app.schemas.runs import (
    BudgetAdjustBody,
    EscalationRead,
    ResolveEscalationBody,
    RunRead,
    RunStartResponse,
    RunTraceRead,
    StopRunBody,
    TraceEventRead,
    TraceMetrics,
    TraceStageSpan,
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


# --- per-run trace ---------------------------------------------------------------------


def _aware(value: datetime.datetime | None) -> datetime.datetime | None:
    """SQLite returns naive datetimes; compare consistently in UTC."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=datetime.UTC)


def _span(execution: StageExecution, events: list[TraceEvent]) -> TraceStageSpan:
    start = _aware(execution.started_at)
    end = _aware(execution.ended_at)
    window = [
        e
        for e in events
        if e.stage == execution.stage
        and (start is None or (_aware(e.timestamp) or start) >= start)
        and (end is None or (_aware(e.timestamp) or end) <= end)
    ]
    llm = [e for e in window if e.kind == "llm_call"]
    tokens = sum(
        int((e.payload or {}).get("input_tokens", 0))
        + int((e.payload or {}).get("output_tokens", 0))
        for e in llm
    )
    return TraceStageSpan(
        stage=execution.stage,
        status=execution.status,
        started_at=execution.started_at,
        ended_at=execution.ended_at,
        duration_seconds=(end - start).total_seconds() if start and end else None,
        loop_back_from=execution.loop_back_from,
        llm_calls=len(llm),
        llm_tokens=tokens,
        source_calls=sum(1 for e in window if e.kind == "source_call"),
    )


@router.get("/runs/{run_id}/trace", response_model=RunTraceRead)
async def get_run_trace(run_id: str, session: AsyncSession = Depends(get_session)) -> RunTraceRead:
    """Internal debugging view: the run's stage spans, every LLM call (model,
    prompt version, exact tokens, duration) and source call, plus run metrics."""
    run = await session.get(Run, run_id)
    if run is None:
        raise NotFound(f"Run {run_id} not found")

    executions = list(
        (
            await session.execute(
                select(StageExecution)
                .where(StageExecution.run_id == run_id)
                .order_by(StageExecution.started_at)
            )
        ).scalars()
    )
    events = list(
        (
            await session.execute(
                select(TraceEvent).where(TraceEvent.run_id == run_id).order_by(TraceEvent.timestamp)
            )
        ).scalars()
    )

    ledger_totals = {
        category: float(total or 0)
        for category, total in (
            await session.execute(
                select(BudgetLedgerEntry.category, func.sum(BudgetLedgerEntry.amount))
                .where(BudgetLedgerEntry.run_id == run_id)
                .group_by(BudgetLedgerEntry.category)
            )
        ).all()
    }
    audit_counts = {
        action: int(count)
        for action, count in (
            await session.execute(
                select(AuditLogEntry.action_type, func.count())
                .where(AuditLogEntry.run_id == run_id)
                .group_by(AuditLogEntry.action_type)
            )
        ).all()
    }

    llm_events = [e for e in events if e.kind == "llm_call"]
    source_events = [e for e in events if e.kind == "source_call"]
    tokens_by_stage: dict[str, int] = {}
    calls_by_prompt: dict[str, int] = {}
    for event in llm_events:
        payload = event.payload or {}
        tokens = int(payload.get("input_tokens", 0)) + int(payload.get("output_tokens", 0))
        stage_key = event.stage or "unknown"
        tokens_by_stage[stage_key] = tokens_by_stage.get(stage_key, 0) + tokens
        prompt = str(payload.get("prompt_version") or "unversioned")
        calls_by_prompt[prompt] = calls_by_prompt.get(prompt, 0) + 1
    calls_by_adapter: dict[str, int] = {}
    for event in source_events:
        adapter = str((event.payload or {}).get("adapter") or "unknown")
        calls_by_adapter[adapter] = calls_by_adapter.get(adapter, 0) + 1

    started, ended = _aware(run.started_at), _aware(run.ended_at)
    metrics = TraceMetrics(
        duration_seconds=(ended - started).total_seconds() if started and ended else None,
        llm_calls=len(llm_events),
        llm_tokens_total=sum(tokens_by_stage.values()),
        llm_tokens_by_stage=tokens_by_stage,
        llm_calls_by_prompt_version=calls_by_prompt,
        source_calls=len(source_events),
        source_calls_by_adapter=calls_by_adapter,
        papers_read=ledger_totals.get("papers_read", 0.0),
        search_calls=ledger_totals.get("search_calls", 0.0),
        escalations=audit_counts.get(AuditActionType.escalation_raised.value, 0),
        loop_backs=audit_counts.get(AuditActionType.loop_back.value, 0),
        errors=audit_counts.get(AuditActionType.error.value, 0),
        budget_consumed=run.budget_consumed,
    )
    return RunTraceRead(
        trace_id=run_id,
        run=RunRead.model_validate(run),
        stages=[_span(e, events) for e in executions],
        events=[TraceEventRead.model_validate(e) for e in events],
        metrics=metrics,
    )
