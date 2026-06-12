"""Integration tests for the run engine, driven synchronously with stub stages
(phase 1 acceptance criteria 1–6)."""

import asyncio

import pytest
from sqlalchemy import select

from app.core.constants import (
    AuditActionType,
    BudgetCategory,
    EscalationStatus,
    EscalationTrigger,
    ProjectStatus,
    Stage,
)
from app.db.models import AuditLogEntry, Escalation, Run, StageExecution
from app.events.bus import InMemoryEventBus, set_event_bus
from app.orchestrator.escalation import resolve_escalation
from app.stages._stubs import StubBehavior, StubStageHandler
from tests.orchestrator_utils import ALL_STAGES, make_engine, make_project, stub_registry


class RecordingBus(InMemoryEventBus):
    def __init__(self) -> None:
        super().__init__()
        self.events = []

    async def publish(self, event) -> None:
        self.events.append(event)
        await super().publish(event)

    def of_type(self, type_: str) -> list:
        return [e for e in self.events if e.type == type_]


@pytest.fixture
def bus() -> RecordingBus:
    recording = RecordingBus()
    set_event_bus(recording)
    return recording


async def _load_run(sessionmaker, run_id):
    async with sessionmaker() as session:
        return await session.get(Run, run_id)


async def _load_project(sessionmaker, project_id):
    async with sessionmaker() as session:
        from app.db.models import Project

        return await session.get(Project, project_id)


async def _executions(sessionmaker, run_id):
    async with sessionmaker() as session:
        result = await session.execute(
            select(StageExecution)
            .where(StageExecution.run_id == run_id)
            .order_by(StageExecution.started_at)
        )
        return result.scalars().all()


async def test_full_stub_pipeline_completes(sessionmaker, bus):
    """Acceptance 1: stubs drive scoping → presentation_generation → complete."""
    registry, handlers = stub_registry()
    engine = make_engine(sessionmaker, bus, registry)
    project = await make_project(sessionmaker)

    run_id = await engine.start(project.id)
    await engine.execute(run_id)

    run = await _load_run(sessionmaker, run_id)
    assert run.status == "complete"
    assert run.stopping_criterion == "coverage"
    assert run.ended_at is not None

    reloaded = await _load_project(sessionmaker, project.id)
    assert reloaded.status == ProjectStatus.complete.value

    executions = await _executions(sessionmaker, run_id)
    assert [e.stage for e in executions] == [s.value for s in ALL_STAGES]
    assert all(e.status == "complete" for e in executions)

    changes = bus.of_type("stage_changed")
    assert [c.payload["to"] for c in changes] == [s.value for s in ALL_STAGES[1:]]
    assert len(bus.of_type("run_finished")) == 1
    assert all(handlers[s].calls == 1 for s in ALL_STAGES)


async def test_loop_back_recorded_and_run_continues(sessionmaker, bus):
    """Acceptance 2: a loop-back is audited, emitted, recorded on the target
    execution, and the run still completes."""
    registry, handlers = stub_registry(
        {
            Stage.paper_analysis: StubBehavior(
                loop_back_to=Stage.literature_search, loop_back_times=1
            )
        }
    )
    engine = make_engine(sessionmaker, bus, registry)
    project = await make_project(sessionmaker)

    run_id = await engine.start(project.id)
    await engine.execute(run_id)

    run = await _load_run(sessionmaker, run_id)
    assert run.status == "complete"

    executions = await _executions(sessionmaker, run_id)
    looped = [e for e in executions if e.loop_back_from is not None]
    assert len(looped) == 1
    assert looped[0].stage == Stage.literature_search.value
    assert looped[0].loop_back_from == Stage.paper_analysis.value

    assert len(bus.of_type("loop_back")) == 1
    async with sessionmaker() as session:
        audits = (
            (
                await session.execute(
                    select(AuditLogEntry).where(
                        AuditLogEntry.action_type == AuditActionType.loop_back.value
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(audits) == 1
    # literature_search ran twice (initial + after loop-back), paper_analysis too.
    assert handlers[Stage.literature_search].calls == 2
    assert handlers[Stage.paper_analysis].calls == 2


async def test_escalation_pauses_and_resume_delivers_response(sessionmaker, bus):
    """Acceptance 3: escalation pauses the run and sets awaiting_input; resolving
    resumes from the raising stage with the response in context."""
    registry, handlers = stub_registry(
        {Stage.comparative_analysis: StubBehavior(escalate_once=True)}
    )
    engine = make_engine(sessionmaker, bus, registry)
    project = await make_project(sessionmaker)

    run_id = await engine.start(project.id)
    await engine.execute(run_id)

    run = await _load_run(sessionmaker, run_id)
    assert run.status == "paused"
    reloaded = await _load_project(sessionmaker, project.id)
    assert reloaded.status == ProjectStatus.awaiting_input.value

    async with sessionmaker() as session:
        escalation = (
            (await session.execute(select(Escalation).where(Escalation.run_id == run_id)))
            .scalars()
            .one()
        )
        assert escalation.status == EscalationStatus.open.value
        assert escalation.trigger == EscalationTrigger.high_stakes.value
        assert len(bus.of_type("escalation_raised")) == 1

        await resolve_escalation(session, escalation.id, {"selected_option": "option_a"})
        await session.commit()

    await engine.resume(run_id)
    await engine.execute(run_id)

    run = await _load_run(sessionmaker, run_id)
    assert run.status == "complete"
    # The raising stage ran twice: once to escalate, once with the response.
    assert handlers[Stage.comparative_analysis].calls == 2
    # Earlier stages were not re-run.
    assert handlers[Stage.scoping].calls == 1


class CrashingHandler(StubStageHandler):
    """Simulates a process kill: dies before doing any work on first entry."""

    def __init__(self, stage: Stage) -> None:
        super().__init__(stage)
        self.crashed = False

    async def run(self, ctx):
        if not self.crashed:
            self.crashed = True
            raise asyncio.CancelledError()
        return await super().run(ctx)


async def test_kill_and_resume_does_not_redo_completed_stages(sessionmaker, bus):
    """Acceptance 4: killing mid-run and resuming continues from the last
    completed stage."""
    registry, handlers = stub_registry()
    crasher = CrashingHandler(Stage.comparative_analysis)
    registry.register(crasher)
    engine = make_engine(sessionmaker, bus, registry)
    project = await make_project(sessionmaker)

    run_id = await engine.start(project.id)
    with pytest.raises(asyncio.CancelledError):
        await engine.execute(run_id)

    # Stages before the kill are durably complete.
    executions = await _executions(sessionmaker, run_id)
    completed = {e.stage for e in executions if e.status == "complete"}
    assert Stage.paper_analysis.value in completed

    await engine.resume(run_id)
    await engine.execute(run_id)

    run = await _load_run(sessionmaker, run_id)
    assert run.status == "complete"
    # Pre-kill stages ran exactly once; the killed stage completed on re-entry.
    assert handlers[Stage.scoping].calls == 1
    assert handlers[Stage.literature_search].calls == 1
    assert handlers[Stage.paper_analysis].calls == 1
    assert crasher.calls == 1  # the crash attempt did no stub work
    executions = await _executions(sessionmaker, run_id)
    assert len([e for e in executions if e.stage == Stage.scoping.value]) == 1


async def test_budget_warning_then_graceful_stop(sessionmaker, bus):
    """Acceptance 5: 80% warning, then a graceful budget stop at the ceiling —
    no crash, stopping_criterion = budget."""
    registry, _ = stub_registry(
        {
            Stage.scoping: StubBehavior(spend=[(BudgetCategory.llm_tokens, 85)]),
            Stage.literature_search: StubBehavior(spend=[(BudgetCategory.llm_tokens, 20)]),
        }
    )
    engine = make_engine(sessionmaker, bus, registry)
    project = await make_project(sessionmaker, budget={"llm_tokens": 100})

    run_id = await engine.start(project.id)
    await engine.execute(run_id)  # must not raise

    run = await _load_run(sessionmaker, run_id)
    assert run.status == "stopped"
    assert run.stopping_criterion == "budget"

    async with sessionmaker() as session:
        actions = {
            a.action_type for a in (await session.execute(select(AuditLogEntry))).scalars().all()
        }
    assert AuditActionType.budget_warning.value in actions
    assert AuditActionType.stopped.value in actions
    finished = bus.of_type("run_finished")
    assert len(finished) == 1
    assert finished[0].payload["stopping_criterion"] == "budget"


async def test_loop_back_cap_converts_to_escalation(sessionmaker, bus):
    """Acceptance 6: the 4th identical loop-back becomes a high_stakes escalation."""
    registry, _ = stub_registry(
        {Stage.paper_analysis: StubBehavior(loop_back_to=Stage.literature_search)}
    )
    engine = make_engine(sessionmaker, bus, registry, loop_back_max=3)
    project = await make_project(sessionmaker)

    run_id = await engine.start(project.id)
    await engine.execute(run_id)

    run = await _load_run(sessionmaker, run_id)
    assert run.status == "paused"

    async with sessionmaker() as session:
        escalation = (
            (await session.execute(select(Escalation).where(Escalation.run_id == run_id)))
            .scalars()
            .one()
        )
    assert escalation.trigger == EscalationTrigger.high_stakes.value
    assert escalation.status == EscalationStatus.open.value
    assert len(bus.of_type("loop_back")) == 3

    executions = await _executions(sessionmaker, run_id)
    looped = [e for e in executions if e.loop_back_from == Stage.paper_analysis.value]
    assert len(looped) == 3


async def test_illegal_loop_back_fails_run(sessionmaker, bus):
    registry, _ = stub_registry({Stage.scoping: StubBehavior(loop_back_to=Stage.report_writing)})
    engine = make_engine(sessionmaker, bus, registry)
    project = await make_project(sessionmaker)

    run_id = await engine.start(project.id)
    await engine.execute(run_id)

    run = await _load_run(sessionmaker, run_id)
    assert run.status == "failed"
    reloaded = await _load_project(sessionmaker, project.id)
    assert reloaded.status == ProjectStatus.failed.value


async def test_unregistered_stage_is_controlled_failure(sessionmaker, bus):
    from app.orchestrator.registry import StageRegistry

    registry = StageRegistry()
    registry.register(StubStageHandler(Stage.scoping))  # nothing else registered
    engine = make_engine(sessionmaker, bus, registry)
    project = await make_project(sessionmaker)

    run_id = await engine.start(project.id)
    await engine.execute(run_id)

    run = await _load_run(sessionmaker, run_id)
    assert run.status == "failed"
    assert len(bus.of_type("error")) == 1


async def test_pause_honored_at_stage_boundary(sessionmaker, bus):
    registry, handlers = stub_registry()
    engine = make_engine(sessionmaker, bus, registry)
    project = await make_project(sessionmaker)

    run_id = await engine.start(project.id)
    await engine.pause(run_id)
    await engine.execute(run_id)  # returns immediately: run is paused

    assert handlers[Stage.scoping].calls == 0
    run = await _load_run(sessionmaker, run_id)
    assert run.status == "paused"

    await engine.resume(run_id)
    await engine.execute(run_id)
    run = await _load_run(sessionmaker, run_id)
    assert run.status == "complete"


async def test_complete_result_ends_run_early(sessionmaker, bus):
    """The Complete branch: a handler can finish the run with its own
    stopping criterion; later stages never execute."""
    from app.core.constants import StoppingCriterion

    registry, handlers = stub_registry(
        {Stage.gap_analysis: StubBehavior(complete_with=StoppingCriterion.stable_map)}
    )
    engine = make_engine(sessionmaker, bus, registry)
    project = await make_project(sessionmaker)

    run_id = await engine.start(project.id)
    await engine.execute(run_id)

    run = await _load_run(sessionmaker, run_id)
    assert run.status == "complete"
    assert run.stopping_criterion == StoppingCriterion.stable_map.value
    reloaded = await _load_project(sessionmaker, project.id)
    assert reloaded.status == ProjectStatus.complete.value
    # Stages after the completing one never ran.
    assert handlers[Stage.report_writing].calls == 0
    assert handlers[Stage.presentation_generation].calls == 0
    assert len(bus.of_type("run_finished")) == 1
