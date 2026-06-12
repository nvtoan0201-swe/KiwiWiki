"""Phase 7 part A: one clean full-pipeline run through all seven real handlers,
with the cross-stage contracts asserted on the durable records:

- provenance survives from extraction into the report (sourced-or-flagged,
  resolvable source ids);
- confidence labels assigned in analysis/gap survive into the report markdown;
- the stopping criterion the search engine recorded is what the report states;
- both deliverables exist and were announced on the event stream.
"""

from sqlalchemy import select

from app.core.constants import Stage
from app.db.models import (
    BudgetLedgerEntry,
    PaperAnalysis,
    Presentation,
    Project,
    Provenance,
    Report,
    Run,
    Source,
    StageExecution,
)
from app.services.citations import cited_source_ids
from tests.e2e.pipeline import (
    FRINGE_TITLE,
    HYBRID_TITLE,
    RECURRENT_TITLE,
    TRANSFORMER_TITLE,
    e2e_engine,
    scripted_llm,
)
from tests.orchestrator_utils import make_project


async def test_clean_run_end_to_end(sessionmaker, bus):
    engine = e2e_engine(sessionmaker, bus, scripted_llm())
    project = await make_project(sessionmaker)

    run_id = await engine.start(project.id)
    await engine.execute(run_id)

    async with sessionmaker() as session:
        run = await session.get(Run, run_id)
        reloaded = await session.get(Project, project.id)
        assert run.status == "complete"
        assert run.stopping_criterion == "coverage"
        assert reloaded.status == "complete"
        assert reloaded.research_question

        # Every stage ran to completion, in order, with no failures.
        executions = (
            (
                await session.execute(
                    select(StageExecution)
                    .where(StageExecution.run_id == run_id)
                    .order_by(StageExecution.started_at)
                )
            )
            .scalars()
            .all()
        )
        assert [e.status for e in executions] == ["complete"] * len(executions)
        assert [e.stage for e in executions] == [s.value for s in Stage]

        # Triage did its job: two deep reads, one skim, one exclusion.
        sources = (
            (await session.execute(select(Source).where(Source.project_id == project.id)))
            .scalars()
            .all()
        )
        by_title = {s.title: s for s in sources}
        assert by_title[TRANSFORMER_TITLE].triage_status == "deep_read"
        assert by_title[RECURRENT_TITLE].triage_status == "deep_read"
        assert by_title[HYBRID_TITLE].triage_status == "skimmed"
        assert by_title[FRINGE_TITLE].triage_status == "excluded"

        # Exactly the three in-scope papers were analyzed.
        analyses = (await session.execute(select(PaperAnalysis))).scalars().all()
        analyzed_sources = {a.source_id for a in analyses}
        assert analyzed_sources == {
            by_title[TRANSFORMER_TITLE].id,
            by_title[RECURRENT_TITLE].id,
            by_title[HYBRID_TITLE].id,
        }

        # --- provenance invariant, end to end ---------------------------------
        provenance = (
            (await session.execute(select(Provenance).where(Provenance.project_id == project.id)))
            .scalars()
            .all()
        )
        assert provenance, "the pipeline must write provenance"
        source_ids = {s.id for s in sources}
        for row in provenance:
            sourced = row.source_id is not None and bool(row.passage and row.passage.strip())
            assert (
                sourced or row.is_inference
            ), f"unsourced, un-flagged claim in {row.context}: {row.claim_text!r}"
            if row.source_id is not None:
                assert row.source_id in source_ids, "provenance must resolve to a stored source"
        contexts = {row.context for row in provenance}
        assert {"analysis", "gap", "report", "presentation"} <= contexts

        # --- the report -------------------------------------------------------
        report = (
            (await session.execute(select(Report).where(Report.project_id == project.id)))
            .scalars()
            .one()
        )
        markdown = report.content_markdown or ""
        # Citations in the markdown resolve to stored sources.
        cited = cited_source_ids(markdown)
        assert cited and set(cited) <= source_ids
        # Confidence labels propagated: claim labels and the gap labels assigned
        # upstream appear, not flattened to uniform prose.
        assert "(confidence: well established" in markdown
        assert "(confidence: emerging" in markdown
        assert "(confidence: contested" in markdown
        # The stopping criterion recorded by the search engine is what the
        # report states.
        search_exec = next(e for e in executions if e.stage == Stage.literature_search.value)
        assert (search_exec.summary or {}).get("stopping") == "saturation"
        assert report.stopping_criterion == "saturation"
        assert "saturation" in markdown

        # --- the presentation ---------------------------------------------------
        deck = (
            (
                await session.execute(
                    select(Presentation).where(Presentation.project_id == project.id)
                )
            )
            .scalars()
            .one()
        )
        assert deck.slides

        # --- budget accounting --------------------------------------------------
        categories = {
            category
            for (category,) in (
                await session.execute(
                    select(BudgetLedgerEntry.category).where(BudgetLedgerEntry.run_id == run_id)
                )
            ).all()
        }
        assert {"llm_tokens", "search_calls", "papers_read"} <= categories
        assert (run.budget_consumed or {}).get("papers_read") == 3.0

    # --- the live event stream announced both deliverables ----------------------
    ready = {e.payload["output"] for e in bus.of_type("output_ready")}
    assert ready == {"report", "presentation"}
    assert bus.of_type("run_finished")[-1].payload["status"] == "complete"
    stages_seen = [e.payload["to"] for e in bus.of_type("stage_changed")]
    assert stages_seen == [s.value for s in Stage][1:]
