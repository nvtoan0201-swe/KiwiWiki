"""Paper analysis handler (phase 3 acceptance 1–7): tiered reading, structured
extraction with provenance, credibility from method, contradiction flags,
missing-subfield loop-back, budget partial coverage, resume idempotency."""

from sqlalchemy import func, select

from app.core.constants import (
    AuditActionType,
    BudgetCategory,
    Stage,
    TriageStatus,
)
from app.db.models import (
    AuditLogEntry,
    BudgetLedgerEntry,
    Contradiction,
    PaperAnalysis,
    Provenance,
    Run,
    Source,
    StageExecution,
)
from app.orchestrator.handler import Advance, LoopBack
from app.schemas.analysis import (
    ContradictionFlag,
    ContradictionJudgment,
    CredibilityAssessment,
    DeepReadExtraction,
    MissingReference,
    SkimExtraction,
)
from app.stages.analysis.credibility import scalar_score
from app.stages.analysis.handler import PaperAnalysisHandler
from tests.llm_fakes import FakeLLM, llm_factory
from tests.orchestrator_utils import make_engine, make_project, stub_registry
from tests.stage_utils import (
    add_source,
    credibility_component,
    make_credibility_responder,
    make_ctx,
    make_deep_read_responder,
    make_skim_responder,
    new_execution,
    topic_embeddings,
)
from tests.test_runner import RecordingBus, bus  # noqa: F401 — fixture reuse

QUESTION = "Do transformers beat RNNs for forecasting?"


_SCHEMAS = {
    cls.__name__: cls
    for cls in (DeepReadExtraction, SkimExtraction, CredibilityAssessment, ContradictionJudgment)
}


def default_llm(**overrides) -> FakeLLM:
    responses = {
        DeepReadExtraction: make_deep_read_responder(),
        SkimExtraction: make_skim_responder(),
        CredibilityAssessment: make_credibility_responder(),
        ContradictionJudgment: [ContradictionJudgment(flags=[])],
    }
    for name, value in overrides.items():
        responses[_SCHEMAS[name]] = value
    return FakeLLM(responses)


async def _analyses(session, project_id):
    rows = await session.execute(
        select(PaperAnalysis)
        .join(Source, Source.id == PaperAnalysis.source_id)
        .where(Source.project_id == project_id)
    )
    return list(rows.scalars())


async def _papers_read_total(session, run_id) -> float:
    total = await session.scalar(
        select(func.sum(BudgetLedgerEntry.amount)).where(
            BudgetLedgerEntry.run_id == run_id,
            BudgetLedgerEntry.category == BudgetCategory.papers_read.value,
        )
    )
    return float(total or 0)


async def test_tiered_records_provenance_and_separated_critique(
    sessionmaker, session, bus  # noqa: F811
):
    """Acceptance 1 + 2: deep reads get full records (numbers included), skims
    get lightweight ones, out-of-scope papers are untouched; every sourced
    claim has a passage and the agent critique is a separate inference."""
    project = await session.merge(await make_project(sessionmaker, research_question=QUESTION))
    deep_a = await add_source(session, project.id, "Deep paper A", status="deep_read")
    deep_b = await add_source(session, project.id, "Deep paper B", status="deep_read")
    skim = await add_source(session, project.id, "Skim paper", status="skimmed", topic="topic2")
    aside = await add_source(session, project.id, "Aside paper", status="set_aside")
    excluded = await add_source(session, project.id, "Excluded paper", status="excluded")

    ctx = await make_ctx(session, bus, project, Stage.paper_analysis, default_llm())
    result = await PaperAnalysisHandler(adapters=[]).run(ctx)

    assert isinstance(result, Advance)
    analyses = await _analyses(session, project.id)
    by_source = {a.source_id: a for a in analyses}
    assert set(by_source) == {deep_a.id, deep_b.id, skim.id}
    assert aside.id not in by_source and excluded.id not in by_source

    deep_record = by_source[deep_a.id]
    assert deep_record.results["depth"] == "deep_read"
    assert "0.91" in deep_record.results["findings"][0]["numbers"]
    assert deep_record.datasets == ["BenchA"]
    assert deep_record.author_limitations[0]["limitation"] == "single-domain evaluation"
    assert deep_record.agent_critique  # separate field, never blended
    assert deep_record.agent_critique not in (deep_record.core_claim or "")
    assert deep_record.confidence_label == "emerging"

    skim_record = by_source[skim.id]
    assert skim_record.results["depth"] == "skim"
    assert skim_record.agent_critique is None
    assert skim_record.datasets is None

    # Provenance: sourced claims carry passages; the critique is inference.
    rows = (
        (await session.execute(select(Provenance).where(Provenance.ref_id == deep_record.id)))
        .scalars()
        .all()
    )
    sourced = [r for r in rows if not r.is_inference]
    inferred = [r for r in rows if r.is_inference]
    assert len(sourced) == 4  # claim, method, finding, limitation
    assert all(r.source_id == deep_a.id and r.passage for r in sourced)
    assert len(inferred) == 1
    assert inferred[0].claim_text == deep_record.agent_critique

    # Budget: one papers_read charge per analyzed paper.
    assert await _papers_read_total(session, ctx.run.id) == 3
    summary = result.summary["analysis"]
    assert summary["coverage"] == "all 3 in-scope papers analyzed"
    assert summary["abstract_only"] == 3  # fixtures have no full text

    audited = (
        (
            await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.action_type == AuditActionType.paper_analyzed.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audited) == 3
    assert all(entry.reasoning for entry in audited)


async def test_skim_upgrades_to_deep_read_on_centrality(sessionmaker, session, bus):  # noqa: F811
    project = await session.merge(await make_project(sessionmaker, research_question=QUESTION))
    source = await add_source(session, project.id, "Sleeper paper", status="skimmed")

    llm = default_llm(
        SkimExtraction=make_skim_responder(upgrade_titles={"Sleeper paper"}),
    )
    ctx = await make_ctx(session, bus, project, Stage.paper_analysis, llm)
    result = await PaperAnalysisHandler(adapters=[]).run(ctx)

    assert isinstance(result, Advance)
    analysis = (await _analyses(session, project.id))[0]
    assert analysis.results["depth"] == "deep_read"  # re-read at full depth
    assert source.triage_status == TriageStatus.deep_read.value
    assert result.summary["analysis"]["upgraded"][0]["source_id"] == source.id

    upgrades = (
        (
            await session.execute(
                select(AuditLogEntry).where(AuditLogEntry.description.like("%depth upgraded%"))
            )
        )
        .scalars()
        .all()
    )
    assert len(upgrades) == 1 and upgrades[0].reasoning


async def test_credibility_scores_method_not_tone(sessionmaker, session, bus):  # noqa: F811
    """Acceptance 3: bold-but-weak scores below rigorous-but-modest."""
    bold = CredibilityAssessment(
        venue_quality=credibility_component(0.5, known=False),
        sample_size_power=credibility_component(0.1),
        methodology_rigor=credibility_component(0.2),
        conflicts_of_interest=credibility_component(0.5, known=False),
        replication_status=credibility_component(0.2),
        summary="Assertive claims, n=12, no controls, unreplicated.",
    )
    rigorous = CredibilityAssessment(
        venue_quality=credibility_component(0.5, known=False),
        sample_size_power=credibility_component(0.9),
        methodology_rigor=credibility_component(0.9),
        conflicts_of_interest=credibility_component(0.5, known=False),
        replication_status=credibility_component(0.7),
        summary="Preregistered, large sample, modest framing.",
    )

    project = await session.merge(await make_project(sessionmaker, research_question=QUESTION))
    bold_src = await add_source(session, project.id, "Bold but weak", status="deep_read")
    rigorous_src = await add_source(
        session, project.id, "Rigorous but modest", status="deep_read", topic="topic2"
    )

    llm = default_llm(
        CredibilityAssessment=make_credibility_responder(
            {"Bold but weak": bold, "Rigorous but modest": rigorous}
        )
    )
    ctx = await make_ctx(session, bus, project, Stage.paper_analysis, llm)
    await PaperAnalysisHandler(adapters=[]).run(ctx)

    assert rigorous_src.credibility_score > bold_src.credibility_score
    assert rigorous_src.credibility_score == scalar_score(rigorous)
    analyses = {a.source_id: a for a in await _analyses(session, project.id)}
    breakdown = analyses[bold_src.id].credibility_breakdown
    assert breakdown["components"]["methodology_rigor"]["score"] == 0.2
    assert breakdown["score"] == bold_src.credibility_score


async def test_conflicting_papers_get_contradiction_row_without_winner(
    sessionmaker, session, bus  # noqa: F811
):
    """Acceptance 4: a contradiction row with both ids, a description,
    resolved=False — and no winner picked."""

    def contradiction_responder(messages):
        prompt = messages[-1]["content"]
        if "Paper up" in prompt and "Paper down" in prompt:
            return ContradictionJudgment(
                flags=[
                    ContradictionFlag(
                        candidate_index=0,
                        description="One reports improvement, the other degradation, same task.",
                    )
                ]
            )
        return ContradictionJudgment(flags=[])

    project = await session.merge(await make_project(sessionmaker, research_question=QUESTION))
    up = await add_source(session, project.id, "Paper up", status="deep_read")
    down = await add_source(session, project.id, "Paper down", status="deep_read")

    llm = default_llm(ContradictionJudgment=contradiction_responder)
    ctx = await make_ctx(session, bus, project, Stage.paper_analysis, llm)
    result = await PaperAnalysisHandler(adapters=[]).run(ctx)

    rows = (
        (await session.execute(select(Contradiction).where(Contradiction.project_id == project.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    row = rows[0]
    assert {row.source_a_id, row.source_b_id} == {up.id, down.id}
    assert row.description
    assert row.resolved is False
    assert row.resolution is None and row.investigation is None  # no winner here
    assert result.summary["analysis"]["contradictions_flagged"] == 1

    flagged = (
        (
            await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.action_type == AuditActionType.contradiction_flagged.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(flagged) == 1


async def test_missing_subfield_loops_back_then_resumes_without_redoing(
    sessionmaker, session, bus  # noqa: F811
):
    """Acceptance 5: repeated references to an absent subfield trigger a
    LoopBack to search with new terms; re-entry skips analyzed papers."""
    missing = [
        MissingReference(
            name="Spectral forecasting theory",
            why_important="Both papers build on it.",
            search_terms=["spectral forecasting survey"],
        )
    ]
    project = await session.merge(await make_project(sessionmaker, research_question=QUESTION))
    await add_source(session, project.id, "Citing paper one", status="deep_read")
    await add_source(session, project.id, "Citing paper two", status="deep_read")

    llm = default_llm(
        DeepReadExtraction=make_deep_read_responder(
            missing_by_title={"Citing paper one": missing, "Citing paper two": missing}
        )
    )
    ctx = await make_ctx(session, bus, project, Stage.paper_analysis, llm)
    handler = PaperAnalysisHandler(adapters=[])
    result = await handler.run(ctx)

    assert isinstance(result, LoopBack)
    assert result.to_stage is Stage.literature_search
    assert "Spectral forecasting theory" in result.reason
    assert result.context["queries"] == ["spectral forecasting survey"]
    assert len(await _analyses(session, project.id)) == 2  # work done before looping

    # Re-entry (as after the search returns): nothing re-analyzed, no
    # double-charge, and the already-counted mentions do not re-trigger.
    charged_before = await _papers_read_total(session, ctx.run.id)
    result_two = await handler.run(await new_execution(ctx))
    assert isinstance(result_two, Advance)
    assert len(await _analyses(session, project.id)) == 2
    assert await _papers_read_total(session, ctx.run.id) == charged_before


async def test_tight_papers_budget_stops_gracefully_with_partial_coverage(
    sessionmaker, bus  # noqa: F811
):
    """Acceptance 6, engine-level: hitting the papers_read ceiling ends the run
    as a graceful budget stop with honest partial coverage — not a crash."""
    project = await make_project(
        sessionmaker,
        research_question=QUESTION,
        budget={"papers_read": 2},
        current_stage=Stage.paper_analysis.value,
    )
    async with sessionmaker() as setup:
        for i in range(4):
            await add_source(setup, project.id, f"Budgeted paper {i}", status="deep_read")
        await setup.commit()

    registry, _ = stub_registry()
    registry.register(PaperAnalysisHandler(adapters=[]))
    fake = default_llm()
    engine = make_engine(
        sessionmaker,
        bus,
        registry,
        llm_factory=llm_factory(fake),
        embeddings=topic_embeddings(),
    )
    run_id = await engine.start(project.id)
    await engine.execute(run_id)  # must not raise

    async with sessionmaker() as check:
        run = await check.get(Run, run_id)
        assert run.status == "stopped"
        assert run.stopping_criterion == "budget"
        execution = (
            (
                await check.execute(
                    select(StageExecution).where(
                        StageExecution.run_id == run_id,
                        StageExecution.stage == Stage.paper_analysis.value,
                    )
                )
            )
            .scalars()
            .one()
        )
        summary = execution.summary["analysis"]
        assert summary["partial"] is True
        assert summary["stopped_on"] == "budget (papers_read)"
        assert summary["coverage"] == "1/4 in-scope papers analyzed; stopped on budget"
        analyses = await check.execute(
            select(func.count())
            .select_from(PaperAnalysis)
            .join(Source, Source.id == PaperAnalysis.source_id)
            .where(Source.project_id == project.id)
        )
        assert analyses.scalar_one() == 1


async def test_reentry_is_idempotent_under_concurrency(
    sessionmaker, session, bus, monkeypatch  # noqa: F811
):
    """Acceptance 7: concurrent batches neither double-charge nor duplicate;
    a second pass skips everything already analyzed."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "analysis_concurrency", 3)
    project = await session.merge(await make_project(sessionmaker, research_question=QUESTION))
    for i in range(5):
        await add_source(
            session, project.id, f"Concurrent paper {i}", status="deep_read", topic="topic9"
        )

    ctx = await make_ctx(session, bus, project, Stage.paper_analysis, default_llm())
    handler = PaperAnalysisHandler(adapters=[])
    assert isinstance(await handler.run(ctx), Advance)
    assert len(await _analyses(session, project.id)) == 5
    assert await _papers_read_total(session, ctx.run.id) == 5

    result = await handler.run(await new_execution(ctx))
    assert isinstance(result, Advance)
    assert len(await _analyses(session, project.id)) == 5  # nothing duplicated
    assert await _papers_read_total(session, ctx.run.id) == 5  # nothing re-charged
    assert result.summary["analysis"]["analyzed_this_execution"] == 0
    assert result.summary["analysis"]["coverage"] == "all 5 in-scope papers analyzed"


async def test_promoted_set_aside_papers_enter_scope(sessionmaker, session, bus):  # noqa: F811
    """A loop-back context can promote set-aside papers into analysis scope."""
    project = await session.merge(await make_project(sessionmaker, research_question=QUESTION))
    aside = await add_source(session, project.id, "Promoted paper", status="set_aside")

    ctx = await make_ctx(
        session,
        bus,
        project,
        Stage.paper_analysis,
        default_llm(),
        loop_back_context={"promote_source_ids": [aside.id]},
    )
    result = await PaperAnalysisHandler(adapters=[]).run(ctx)

    assert isinstance(result, Advance)
    assert aside.triage_status == TriageStatus.skimmed.value
    analyses = await _analyses(session, project.id)
    assert [a.source_id for a in analyses] == [aside.id]
