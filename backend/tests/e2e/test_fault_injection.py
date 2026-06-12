"""Phase 7 part D: fault injection against the engine.

- A persistent LLM failure fails the stage *cleanly*: the run ends `failed`
  with an audited error, committed work survives as a resumable checkpoint,
  and a fresh run on the same project finishes the job without redoing it.
- A process kill at every stage boundary (first entry of each stage) resumes
  to an identical completed state with no duplicated work.
"""

import asyncio

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.constants import Stage
from app.core.errors import LLMError
from app.db.models import AuditLogEntry, PaperAnalysis, Report, Run, StageExecution
from app.orchestrator.handler import StageContext, StageHandler, StageResult
from app.orchestrator.registry import StageRegistry
from app.orchestrator.runner import RunEngine
from tests.e2e.pipeline import (
    RECURRENT_TITLE,
    build_e2e_registry,
    corpus_adapter,
    e2e_engine,
    scripted_llm,
)
from tests.llm_fakes import llm_factory
from tests.orchestrator_utils import make_project
from tests.stage_utils import make_deep_read_responder, title_from_prompt, topic_embeddings


def persistent_llm_failure(fail_titles: set[str]):
    """A deep-read responder that fails like the wrapper does after exhausting
    its retries: a typed LLMError, every time."""
    base = make_deep_read_responder()

    def respond(messages):
        title = title_from_prompt(messages)
        if title in fail_titles:
            raise LLMError(f"LLM call failed after retries while reading {title}")
        return base(messages)

    return respond


async def test_persistent_llm_failure_fails_stage_cleanly_and_is_resumable(
    sessionmaker, bus, monkeypatch
):
    monkeypatch.setattr(get_settings(), "analysis_concurrency", 1)

    fake = scripted_llm(deep_read_responder=persistent_llm_failure({RECURRENT_TITLE}))
    engine = e2e_engine(sessionmaker, bus, fake)
    project = await make_project(sessionmaker)

    run_id = await engine.start(project.id)
    await engine.execute(run_id)  # must not raise: the failure is contained

    async with sessionmaker() as session:
        run = await session.get(Run, run_id)
        assert run.status == "failed"
        assert run.stopping_criterion == "error"
        # The checkpointed work before the failure survived.
        analyses = (await session.execute(select(PaperAnalysis))).scalars().all()
        assert len(analyses) == 1
        # The failure is on the audit record.
        errors = (
            (
                await session.execute(
                    select(AuditLogEntry).where(
                        AuditLogEntry.project_id == project.id,
                        AuditLogEntry.action_type == "error",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert any("LLM call failed" in (e.description or "") for e in errors)

    # A new run on the same project (the LLM is healthy again) picks up at the
    # checkpoint: the analyzed paper is not redone, and the project completes.
    engine2 = e2e_engine(sessionmaker, bus, scripted_llm())
    run2 = await engine2.start(project.id)
    await engine2.execute(run2)

    async with sessionmaker() as session:
        run = await session.get(Run, run2)
        assert run.status == "complete"
        analyses = (await session.execute(select(PaperAnalysis))).scalars().all()
        assert len(analyses) == 3
        assert len({a.source_id for a in analyses}) == 3
        (
            (await session.execute(select(Report).where(Report.project_id == project.id)))
            .scalars()
            .one()
        )


class KillOnFirstEntry(StageHandler):
    """Simulates a process death at the stage boundary: the first time each
    stage is entered, the task dies before the stage does any work."""

    def __init__(self, inner: StageHandler) -> None:
        self.stage = inner.stage
        self._inner = inner
        self.killed = False

    async def run(self, ctx: StageContext) -> StageResult:
        if not self.killed:
            self.killed = True
            raise asyncio.CancelledError(f"killed entering {self.stage.value}")
        return await self._inner.run(ctx)


async def test_kill_at_every_stage_boundary_resumes_without_duplicates(sessionmaker, bus):
    inner = build_e2e_registry([corpus_adapter()])
    registry = StageRegistry()
    for stage in Stage:
        registry.register(KillOnFirstEntry(inner.get(stage)))

    engine = RunEngine(
        sessionmaker,
        registry=registry,
        bus=bus,
        llm_factory=llm_factory(scripted_llm()),
        embeddings=topic_embeddings(),
    )
    project = await make_project(sessionmaker)
    run_id = await engine.start(project.id)

    kills = 0
    for _ in range(len(Stage) + 1):
        try:
            await engine.execute(run_id)
            break
        except asyncio.CancelledError:
            kills += 1
            await engine.resume(run_id)
    else:
        pytest.fail("run never completed")
    assert kills == len(Stage)  # one death per stage boundary

    async with sessionmaker() as session:
        run = await session.get(Run, run_id)
        assert run.status == "complete"
        # Exactly one execution per stage: the killed entries left no debris.
        per_stage = {
            stage: count
            for stage, count in (
                await session.execute(
                    select(StageExecution.stage, func.count())
                    .where(StageExecution.run_id == run_id)
                    .group_by(StageExecution.stage)
                )
            ).all()
        }
        assert per_stage == {stage.value: 1 for stage in Stage}
        # No duplicated analysis work, one report.
        analyses = (await session.execute(select(PaperAnalysis))).scalars().all()
        assert len(analyses) == len({a.source_id for a in analyses}) == 3
        report = (
            (await session.execute(select(Report).where(Report.project_id == project.id)))
            .scalars()
            .one()
        )
        assert report.version == 1
