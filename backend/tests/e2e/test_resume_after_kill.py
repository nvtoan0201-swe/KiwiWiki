"""Phase 7 part A: kill the process mid-analysis, resume, and get the same
final outputs as an uninterrupted run — without duplicated work.

The "kill" is an `asyncio.CancelledError` raised from inside the second
paper's extraction (exactly what task cancellation / process death looks like
to the engine): the engine re-raises without converting it into a failure, so
the run stays `running` at its last committed checkpoint. A fresh engine and a
fresh scripted LLM (a new process, in effect) resume it to completion.
"""

import asyncio

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.constants import Stage
from app.db.models import BudgetLedgerEntry, PaperAnalysis, Report, Source, StageExecution
from tests.e2e.pipeline import RECURRENT_TITLE, e2e_engine, normalize_ids, scripted_llm
from tests.orchestrator_utils import make_project
from tests.stage_utils import make_deep_read_responder, title_from_prompt


def killing_deep_responder(kill_titles: set[str]):
    base = make_deep_read_responder()

    def respond(messages):
        title = title_from_prompt(messages)
        if title in kill_titles:
            raise asyncio.CancelledError(f"process killed while reading {title}")
        return base(messages)

    return respond


async def _normalized_report(sessionmaker, project_id: str) -> str:
    async with sessionmaker() as session:
        report = (
            (await session.execute(select(Report).where(Report.project_id == project_id)))
            .scalars()
            .one()
        )
        sources = (
            (await session.execute(select(Source).where(Source.project_id == project_id)))
            .scalars()
            .all()
        )
    return normalize_ids(report.content_markdown or "", {s.id: f"<{s.title}>" for s in sources})


async def test_kill_mid_analysis_then_resume(sessionmaker, bus, monkeypatch):
    # One paper per batch so the kill lands between durable checkpoints.
    monkeypatch.setattr(get_settings(), "analysis_concurrency", 1)

    fake = scripted_llm(deep_read_responder=killing_deep_responder({RECURRENT_TITLE}))
    engine = e2e_engine(sessionmaker, bus, fake)
    project = await make_project(sessionmaker)

    run_id = await engine.start(project.id)
    with pytest.raises(asyncio.CancelledError):
        await engine.execute(run_id)

    # Killed, not failed: the last committed checkpoint is the durable state.
    async with sessionmaker() as session:
        analyzed = (await session.execute(select(PaperAnalysis))).scalars().all()
        assert len(analyzed) == 1, "exactly the first batch was committed before the kill"

    # A new process: fresh engine, fresh scripted LLM, resume the same run.
    engine2 = e2e_engine(sessionmaker, bus, scripted_llm())
    await engine2.resume(run_id)
    await engine2.execute(run_id)

    async with sessionmaker() as session:
        # No duplicated work: one analysis per in-scope source...
        analyses = (await session.execute(select(PaperAnalysis))).scalars().all()
        assert len(analyses) == 3
        assert len({a.source_id for a in analyses}) == 3
        # ...one paper_analysis execution (re-entered, not restarted)...
        analysis_executions = await session.scalar(
            select(func.count())
            .select_from(StageExecution)
            .where(
                StageExecution.run_id == run_id,
                StageExecution.stage == Stage.paper_analysis.value,
            )
        )
        assert analysis_executions == 1
        # ...and each paper charged `papers_read` exactly once (the killed
        # paper's uncommitted charge was rolled back with the kill).
        papers_charged = await session.scalar(
            select(func.count())
            .select_from(BudgetLedgerEntry)
            .where(
                BudgetLedgerEntry.run_id == run_id,
                BudgetLedgerEntry.category == "papers_read",
            )
        )
        assert papers_charged == 3

    # The resumed run's outputs are identical to an uninterrupted run's
    # (modulo per-project ids, which are normalized away).
    control_engine = e2e_engine(sessionmaker, bus, scripted_llm())
    control_project = await make_project(sessionmaker)
    control_run = await control_engine.start(control_project.id)
    await control_engine.execute(control_run)

    resumed_report = await _normalized_report(sessionmaker, project.id)
    control_report = await _normalized_report(sessionmaker, control_project.id)
    assert resumed_report == control_report
