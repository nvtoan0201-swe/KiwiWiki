"""The run engine: drives a project through the workflow stages.

One loop iteration = one stage step, executed in its own DB session and
committed before the next step. That makes every step durable: a killed
process resumes from the last completed stage, and pause/stop/budget changes
made through the API become visible between steps.

The engine is transport-agnostic: `execute(run_id)` is a plain coroutine the
tests drive directly; `launch(run_id)` runs it as an in-process background
task (the seam where an external worker, e.g. arq, can attach later).
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.embeddings.client import EmbeddingsClient
from app.adapters.llm.client import LLMClient, UsageCallback
from app.core.config import get_settings
from app.core.constants import (
    AuditActionType,
    BudgetCategory,
    EscalationTrigger,
    ProjectStatus,
    Stage,
    StoppingCriterion,
)
from app.core.errors import AppError, BudgetExceeded, NotFound, ValidationError
from app.db.models import Project, Run, StageExecution
from app.db.session import get_sessionmaker
from app.events.bus import EventBus, get_event_bus
from app.events.publisher import EventPublisher
from app.orchestrator import escalation as escalation_service
from app.orchestrator import state_machine
from app.orchestrator.budget import BudgetGuard
from app.orchestrator.handler import (
    Advance,
    Complete,
    Escalate,
    Fail,
    LLMFactory,
    LoopBack,
    StageContext,
    StageResult,
)
from app.orchestrator.registry import StageRegistry
from app.services.audit import AuditService

logger = logging.getLogger("app.orchestrator")

# Run.status vocabulary. (Projects reuse ProjectStatus; runs have their own
# lifecycle: a run never goes back to draft, and a budget/user stop is final.)
RUN_RUNNING = "running"
RUN_PAUSED = "paused"
RUN_COMPLETE = "complete"
RUN_FAILED = "failed"
RUN_STOPPED = "stopped"

_ACTIVE_RUN_STATUSES = {RUN_RUNNING}
_RESUMABLE_RUN_STATUSES = {RUN_PAUSED, RUN_RUNNING}


def _default_llm_factory(on_usage: UsageCallback | None) -> LLMClient:
    return LLMClient(on_usage=on_usage)


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class RunEngine:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        *,
        registry: StageRegistry | None = None,
        bus: EventBus | None = None,
        llm_factory: LLMFactory | None = None,
        embeddings: EmbeddingsClient | None = None,
        loop_back_max: int | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._registry = registry
        self._bus = bus
        self._llm_factory: LLMFactory = llm_factory or _default_llm_factory
        self._embeddings = embeddings or EmbeddingsClient()
        settings = get_settings()
        self._loop_back_max = loop_back_max if loop_back_max is not None else settings.loop_back_max
        self._tasks: dict[str, asyncio.Task[None]] = {}

    # --- collaborators (resolved lazily so tests can construct cheaply) -----------

    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        if self._sessionmaker is None:
            self._sessionmaker = get_sessionmaker()
        return self._sessionmaker

    def _get_registry(self) -> StageRegistry:
        if self._registry is None:
            from app.stages import build_default_registry

            self._registry = build_default_registry()
        return self._registry

    def _get_bus(self) -> EventBus:
        if self._bus is None:
            self._bus = get_event_bus()
        return self._bus

    # --- lifecycle -----------------------------------------------------------------

    async def start(self, project_id: str) -> str:
        """Create a run for the project and mark it running. Caller launches it."""
        async with self.sessionmaker()() as session:
            project = await session.get(Project, project_id)
            if project is None:
                raise NotFound(f"Project {project_id} not found")
            active = await session.scalar(
                select(func.count())
                .select_from(Run)
                .where(Run.project_id == project_id, Run.status.in_(_RESUMABLE_RUN_STATUSES))
            )
            if active:
                raise ValidationError(f"Project {project_id} already has an active run")

            run = Run(project_id=project_id, status=RUN_RUNNING, started_at=_utcnow())
            session.add(run)
            project.status = ProjectStatus.running.value
            if project.current_stage is None:
                project.current_stage = state_machine.FIRST_STAGE.value
            await session.flush()
            run_id = run.id
            await session.commit()
        return run_id

    def launch(self, run_id: str) -> asyncio.Task[None]:
        """Run `execute` as an in-process background task."""
        existing = self._tasks.get(run_id)
        if existing is not None and not existing.done():
            return existing
        task = asyncio.create_task(self.execute(run_id), name=f"run:{run_id}")
        self._tasks[run_id] = task
        return task

    async def join(self, run_id: str) -> None:
        """Wait for a launched run to settle (tests and graceful shutdown)."""
        task = self._tasks.get(run_id)
        if task is not None:
            await task

    async def pause(self, run_id: str) -> None:
        """Request a pause; the engine honors it at the next stage boundary."""
        async with self.sessionmaker()() as session:
            run = await self._get_run(session, run_id)
            if run.status not in _RESUMABLE_RUN_STATUSES:
                raise ValidationError(f"Run {run_id} is {run.status}; cannot pause")
            run.status = RUN_PAUSED
            project = await session.get(Project, run.project_id)
            if project is not None and project.status == ProjectStatus.running.value:
                project.status = ProjectStatus.paused.value
            await session.commit()

    async def resume(self, run_id: str) -> str:
        """Mark a paused (or interrupted) run runnable again. Caller launches it."""
        async with self.sessionmaker()() as session:
            run = await self._get_run(session, run_id)
            if run.status not in _RESUMABLE_RUN_STATUSES:
                raise ValidationError(f"Run {run_id} is {run.status}; cannot resume")
            run.status = RUN_RUNNING
            project = await session.get(Project, run.project_id)
            if project is not None:
                project.status = ProjectStatus.running.value
            await session.commit()
        return run_id

    async def stop(self, run_id: str, reason: str | None = None) -> None:
        async with self.sessionmaker()() as session:
            run = await self._get_run(session, run_id)
            if run.status in {RUN_COMPLETE, RUN_FAILED, RUN_STOPPED}:
                raise ValidationError(f"Run {run_id} is already {run.status}")
            run.status = RUN_STOPPED
            run.stopping_criterion = StoppingCriterion.user_stopped.value
            run.ended_at = _utcnow()
            project = await session.get(Project, run.project_id)
            if project is not None:
                project.status = ProjectStatus.paused.value
            audit = AuditService(session, self._get_bus())
            await audit.record(
                project_id=run.project_id,
                action_type=AuditActionType.stopped,
                description="Run stopped by user",
                reasoning=reason or "User requested the run be stopped.",
                run_id=run.id,
                stage=project.current_stage if project else None,
            )
            await EventPublisher(self._get_bus(), run.project_id, run.id).emit(
                "run_finished",
                payload={"status": RUN_STOPPED, "stopping_criterion": run.stopping_criterion},
            )
            await session.commit()

    # --- main loop -----------------------------------------------------------------

    async def execute(self, run_id: str) -> None:
        """Advance the run one stage at a time until it completes, pauses, fails,
        or is stopped. Each step commits before the next begins (resumability)."""
        while True:
            should_continue = await self._step(run_id)
            if not should_continue:
                return

    async def _step(self, run_id: str) -> bool:
        async with self.sessionmaker()() as session:
            run = await self._get_run(session, run_id)
            if run.status not in _ACTIVE_RUN_STATUSES:
                return False
            project = await session.get(Project, run.project_id)
            if project is None:
                return False

            stage = Stage(project.current_stage or state_machine.FIRST_STAGE.value)
            bus = self._get_bus()
            audit = AuditService(session, bus)
            events = EventPublisher(bus, project.id, run.id)
            guard = await BudgetGuard.create(
                session, run, project, audit, events, stage=stage.value
            )

            execution, is_new = await self._get_or_create_execution(session, run, stage)
            if is_new:
                await audit.record(
                    project_id=project.id,
                    action_type=AuditActionType.stage_start,
                    description=f"Stage started: {stage.value}",
                    reasoning="The workflow advanced to this stage.",
                    run_id=run.id,
                    stage=stage.value,
                )

            resolved = await escalation_service.latest_resolved_for_stage(
                session, run, stage.value, execution.started_at
            )
            ctx = StageContext(
                session=session,
                project=project,
                run=run,
                stage_execution=execution,
                budget=guard,
                audit=audit,
                events=events,
                embeddings=self._embeddings,
                llm_factory=self._llm_factory,
                escalation_response=resolved.user_response if resolved else None,
                loop_back_context=(execution.summary or {}).get("_loop_back_context"),
            )

            stage_started = _utcnow()
            try:
                handler = self._get_registry().get(stage)
                result: StageResult = await handler.run(ctx)
            except BudgetExceeded as exc:
                await self._finish_budget_stop(session, run, project, audit, events, stage, exc)
                await session.commit()
                return False
            except asyncio.CancelledError:
                # Process kill / task cancellation: leave state as last committed.
                raise
            except AppError as exc:
                result = Fail(f"{exc.code}: {exc.message}")
            except Exception as exc:  # noqa: BLE001 — a handler bug fails the run, not the API
                logger.exception("stage handler crashed", extra={"extra": {"stage": stage.value}})
                result = Fail(str(exc))

            # Wall-clock spent inside the handler counts against the time budget.
            elapsed = (_utcnow() - stage_started).total_seconds()
            try:
                if elapsed >= 1.0:
                    await guard.charge(BudgetCategory.time, elapsed, note=f"stage {stage.value}")
            except BudgetExceeded as exc:
                await self._finish_budget_stop(session, run, project, audit, events, stage, exc)
                await session.commit()
                return False

            should_continue = await self._apply_result(
                session, run, project, execution, stage, result, audit, events, guard
            )
            await session.commit()
            return should_continue

    # --- result interpretation -------------------------------------------------------

    async def _apply_result(
        self,
        session: AsyncSession,
        run: Run,
        project: Project,
        execution: StageExecution,
        stage: Stage,
        result: StageResult,
        audit: AuditService,
        events: EventPublisher,
        guard: BudgetGuard,
    ) -> bool:
        if isinstance(result, Advance):
            self._close_execution(execution, "complete", result.summary)
            await audit.record(
                project_id=project.id,
                action_type=AuditActionType.stage_complete,
                description=f"Stage complete: {stage.value}",
                reasoning="The stage handler finished and advanced the workflow.",
                payload={"summary": result.summary},
                run_id=run.id,
                stage=stage.value,
            )
            following = state_machine.next_stage(stage)
            if following is None:
                await self._finish_run(run, project, audit, events, StoppingCriterion.coverage)
                return False
            project.current_stage = following.value
            await events.emit(
                "stage_changed",
                stage=following.value,
                payload={"from": stage.value, "to": following.value},
            )
            return True

        if isinstance(result, LoopBack):
            return await self._apply_loop_back(
                session, run, project, execution, stage, result, audit, events
            )

        if isinstance(result, Escalate):
            await escalation_service.raise_escalation(
                session,
                audit,
                events,
                project=project,
                run=run,
                stage=stage.value,
                trigger=result.trigger,
                question=result.question,
                context=result.context,
                options=result.options,
            )
            # The stage execution stays "running"; the handler re-enters on resume.
            return False

        if isinstance(result, Complete):
            self._close_execution(execution, "complete", result.summary)
            await self._finish_run(run, project, audit, events, result.stopping_criterion)
            return False

        if isinstance(result, Fail):
            self._close_execution(execution, "failed", {"error": result.error})
            run.status = RUN_FAILED
            run.stopping_criterion = StoppingCriterion.error.value
            run.ended_at = _utcnow()
            project.status = ProjectStatus.failed.value
            await audit.record(
                project_id=project.id,
                action_type=AuditActionType.error,
                description=f"Stage {stage.value} failed: {result.error}",
                reasoning="The stage handler reported an unrecoverable failure.",
                run_id=run.id,
                stage=stage.value,
            )
            await events.emit("error", stage=stage.value, payload={"message": result.error})
            return False

        raise AssertionError(f"Unhandled StageResult: {result!r}")

    async def _apply_loop_back(
        self,
        session: AsyncSession,
        run: Run,
        project: Project,
        execution: StageExecution,
        stage: Stage,
        result: LoopBack,
        audit: AuditService,
        events: EventPublisher,
    ) -> bool:
        target = result.to_stage
        if not state_machine.can_loop_back(stage, target):
            self._close_execution(
                execution, "failed", {"error": f"illegal loop-back {stage.value}->{target.value}"}
            )
            run.status = RUN_FAILED
            run.stopping_criterion = StoppingCriterion.error.value
            run.ended_at = _utcnow()
            project.status = ProjectStatus.failed.value
            await audit.record(
                project_id=project.id,
                action_type=AuditActionType.error,
                description=(f"Illegal loop-back from {stage.value} to {target.value} rejected"),
                reasoning="The transition table does not permit this loop-back.",
                run_id=run.id,
                stage=stage.value,
            )
            return False

        prior = await session.scalar(
            select(func.count())
            .select_from(StageExecution)
            .where(
                StageExecution.run_id == run.id,
                StageExecution.stage == target.value,
                StageExecution.loop_back_from == stage.value,
            )
        )
        if (prior or 0) >= self._loop_back_max:
            await escalation_service.raise_escalation(
                session,
                audit,
                events,
                project=project,
                run=run,
                stage=stage.value,
                trigger=EscalationTrigger.high_stakes,
                question=(
                    f"The agent has looped back from {stage.value} to {target.value} "
                    f"{prior} times and appears stuck. How should it proceed?"
                ),
                context={"loop_back_reason": result.reason, "loop_back_count": prior},
                options=[
                    {"id": "loop_again", "label": f"Try {target.value} once more"},
                    {"id": "proceed", "label": f"Continue from {stage.value} as-is"},
                    {"id": "stop", "label": "Stop the run"},
                ],
            )
            return False

        self._close_execution(
            execution,
            "complete",
            {**(result.summary or {}), "loop_back_to": target.value, "reason": result.reason},
        )
        target_execution = StageExecution(
            run_id=run.id,
            stage=target.value,
            status="running",
            started_at=_utcnow(),
            loop_back_from=stage.value,
            summary={"_loop_back_context": result.context} if result.context else None,
        )
        session.add(target_execution)
        project.current_stage = target.value
        await session.flush()

        await audit.record(
            project_id=project.id,
            action_type=AuditActionType.loop_back,
            description=f"Loop-back: {stage.value} → {target.value}",
            reasoning=result.reason,
            payload={"from": stage.value, "to": target.value, "context": result.context},
            run_id=run.id,
            stage=stage.value,
        )
        await events.emit(
            "loop_back",
            stage=target.value,
            payload={"from": stage.value, "to": target.value, "reason": result.reason},
        )
        await events.emit(
            "stage_changed",
            stage=target.value,
            payload={"from": stage.value, "to": target.value, "loop_back": True},
        )
        return True

    # --- terminal transitions ----------------------------------------------------------

    async def _finish_run(
        self,
        run: Run,
        project: Project,
        audit: AuditService,
        events: EventPublisher,
        criterion: StoppingCriterion,
    ) -> None:
        run.status = RUN_COMPLETE
        run.stopping_criterion = criterion.value
        run.ended_at = _utcnow()
        project.status = ProjectStatus.complete.value
        await audit.record(
            project_id=project.id,
            action_type=AuditActionType.stage_complete,
            description="Run finished",
            reasoning=f"Stopping criterion: {criterion.value}.",
            run_id=run.id,
        )
        await events.emit(
            "run_finished",
            payload={"status": RUN_COMPLETE, "stopping_criterion": criterion.value},
        )

    async def _finish_budget_stop(
        self,
        session: AsyncSession,
        run: Run,
        project: Project,
        audit: AuditService,
        events: EventPublisher,
        stage: Stage,
        exc: BudgetExceeded,
    ) -> None:
        """A ceiling was hit: stop gracefully with whatever exists — never a crash."""
        run.status = RUN_STOPPED
        run.stopping_criterion = StoppingCriterion.budget.value
        run.ended_at = _utcnow()
        project.status = ProjectStatus.complete.value
        await audit.record(
            project_id=project.id,
            action_type=AuditActionType.stopped,
            description=f"Run stopped: budget ceiling reached ({exc.details.get('category')})",
            reasoning=(
                "A budget ceiling was reached; the run ends gracefully and outputs "
                "are produced from the work completed so far."
            ),
            payload=exc.details,
            run_id=run.id,
            stage=stage.value,
        )
        await events.emit(
            "run_finished",
            stage=stage.value,
            payload={
                "status": RUN_STOPPED,
                "stopping_criterion": StoppingCriterion.budget.value,
                "detail": exc.details,
            },
        )

    # --- helpers ---------------------------------------------------------------------

    @staticmethod
    def _close_execution(
        execution: StageExecution, status: str, summary: dict[str, Any] | None
    ) -> None:
        execution.status = status
        execution.ended_at = _utcnow()
        if summary is not None:
            existing = {
                k: v for k, v in (execution.summary or {}).items() if k == "_loop_back_context"
            }
            execution.summary = {**existing, **summary}

    @staticmethod
    async def _get_or_create_execution(
        session: AsyncSession, run: Run, stage: Stage
    ) -> tuple[StageExecution, bool]:
        result = await session.execute(
            select(StageExecution)
            .where(
                StageExecution.run_id == run.id,
                StageExecution.stage == stage.value,
                StageExecution.status == "running",
            )
            .order_by(StageExecution.started_at.desc())
            .limit(1)
        )
        execution = result.scalars().first()
        if execution is not None:
            return execution, False
        execution = StageExecution(
            run_id=run.id, stage=stage.value, status="running", started_at=_utcnow()
        )
        session.add(execution)
        await session.flush()
        return execution, True

    @staticmethod
    async def _get_run(session: AsyncSession, run_id: str) -> Run:
        run = await session.get(Run, run_id)
        if run is None:
            raise NotFound(f"Run {run_id} not found")
        return run


# --- module-level engine (mirrors the event-bus accessor pattern) ---------------------

_engine: RunEngine | None = None


def get_run_engine() -> RunEngine:
    global _engine
    if _engine is None:
        _engine = RunEngine()
    return _engine


def set_run_engine(engine: RunEngine | None) -> None:
    global _engine
    _engine = engine
