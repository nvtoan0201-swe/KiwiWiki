"""Phase 7 part A: a full run that loops back (analysis → literature_search).

Two deep reads name the same missing foundational work; analysis loops back
with its search terms, the second search execution surfaces the Kalman paper,
analysis re-enters without redoing the already-analyzed papers, and the run
still completes with both deliverables.
"""

from sqlalchemy import select

from app.core.constants import Stage
from app.db.models import AuditLogEntry, PaperAnalysis, Report, Run, Source, StageExecution
from tests.e2e.pipeline import (
    KALMAN_TITLE,
    corpus_adapter,
    e2e_engine,
    missing_kalman_references,
    scripted_llm,
)
from tests.orchestrator_utils import make_project


async def test_loop_back_run_completes(sessionmaker, bus):
    fake = scripted_llm(missing_by_title=missing_kalman_references())
    engine = e2e_engine(sessionmaker, bus, fake, adapters=[corpus_adapter(with_kalman=True)])
    project = await make_project(sessionmaker)

    run_id = await engine.start(project.id)
    await engine.execute(run_id)

    async with sessionmaker() as session:
        run = await session.get(Run, run_id)
        assert run.status == "complete"

        # The loop-back happened: a second literature_search execution exists,
        # marked with where it came from.
        searches = (
            (
                await session.execute(
                    select(StageExecution)
                    .where(
                        StageExecution.run_id == run_id,
                        StageExecution.stage == Stage.literature_search.value,
                    )
                    .order_by(StageExecution.started_at)
                )
            )
            .scalars()
            .all()
        )
        assert len(searches) == 2
        assert searches[1].loop_back_from == Stage.paper_analysis.value

        # The loop-back query surfaced the missing paper, and it was analyzed.
        kalman = (
            (await session.execute(select(Source).where(Source.title == KALMAN_TITLE)))
            .scalars()
            .one()
        )
        assert kalman.triage_status == "deep_read"
        analyses = (await session.execute(select(PaperAnalysis))).scalars().all()
        assert kalman.id in {a.source_id for a in analyses}

        # Re-entry did not duplicate: one analysis per analyzed source.
        analyzed = [a.source_id for a in analyses]
        assert len(analyzed) == len(set(analyzed)) == 4

        # The loop-back is on the durable record with its reasoning.
        loop_audits = (
            (
                await session.execute(
                    select(AuditLogEntry).where(
                        AuditLogEntry.project_id == project.id,
                        AuditLogEntry.action_type == "loop_back",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(loop_audits) == 1
        assert "Kalman" in (loop_audits[0].reasoning or "")

        # And the run still produced its deliverables.
        report = (
            (await session.execute(select(Report).where(Report.project_id == project.id)))
            .scalars()
            .one()
        )
        assert report.content_markdown

    loop_events = bus.of_type("loop_back")
    assert len(loop_events) == 1
    assert loop_events[0].payload["from"] == Stage.paper_analysis.value
    assert loop_events[0].payload["to"] == Stage.literature_search.value
